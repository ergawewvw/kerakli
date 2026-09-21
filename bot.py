import os
import asyncio
import random
import sqlite3
import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import web
from openai import AsyncOpenAI

from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi!")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY topilmadi!")

ai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
AI_MODEL = "gpt-5.6-luna"

TZ = ZoneInfo("Asia/Tashkent")
DB_FILE = "manager.db"

# Render Environment Variables orqali o'rnatiladi.
# Faqat shu Telegram ID /adminstats komandadan foydalana oladi.
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()

scheduler = AsyncIOScheduler(
    timezone=TZ
)


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

cursor = db.cursor()


cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    channel TEXT
)
""")

# Foydalanuvchi nomi va username uchun eski bazani avtomatik yangilaymiz.
for column_sql in [
    "ALTER TABLE users ADD COLUMN first_name TEXT",
    "ALTER TABLE users ADD COLUMN username TEXT",
]:
    try:
        cursor.execute(column_sql)
    except sqlite3.OperationalError:
        pass



cursor.execute("""
CREATE TABLE IF NOT EXISTS stickers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    file_id TEXT NOT NULL
)
""")


cursor.execute("""
CREATE TABLE IF NOT EXISTS scheduled_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    from_chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    send_time TEXT NOT NULL,
    sticker_category TEXT,
    status TEXT DEFAULT 'pending'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS ai_usage (
    user_id INTEGER PRIMARY KEY,
    request_count INTEGER DEFAULT 0
)
""")

db.commit()

# Takroriy postlar
cursor.execute("""
CREATE TABLE IF NOT EXISTS repeating_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    from_chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    interval_type TEXT NOT NULL,
    next_time TEXT NOT NULL,
    sticker_category TEXT,
    status TEXT DEFAULT 'active'
)
""")

# Qo'shimcha adminlar
cursor.execute("""
CREATE TABLE IF NOT EXISTS bot_admins (
    user_id INTEGER PRIMARY KEY
)
""")
db.commit()


# =========================================================
# MULTI-CHANNEL DATABASE
# =========================================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    UNIQUE(user_id, channel)
)
""")

# Eski bitta kanal formatini yangi ko'p-kanalli jadvalga bir marta ko'chiramiz.
cursor.execute("""
INSERT OR IGNORE INTO user_channels (user_id, channel)
SELECT user_id, channel FROM users
WHERE channel IS NOT NULL AND channel != ''
""")
db.commit()


# =========================================================
# STATES
# =========================================================

class SetupState(StatesGroup):
    waiting_channel = State()
    waiting_confirmation = State()
    waiting_time = State()
    waiting_channel_selection = State()
    waiting_delete_channel = State()


class StickerState(StatesGroup):
    waiting_category = State()
    waiting_sticker = State()


class EditPostState(StatesGroup):
    waiting_replacement = State()


class PreviewState(StatesGroup):
    waiting_confirmation = State()


class RepeatState(StatesGroup):
    waiting_interval = State()


class AdminState(StatesGroup):
    waiting_admin_id = State()


# =========================================================
# DATABASE FUNCTIONS
# =========================================================

def register_user(user):
    """Foydalanuvchining faqat ism va username'ini saqlaydi."""
    first_name = user.first_name or ""
    username = user.username or ""

    cursor.execute("""
        INSERT INTO users (user_id, first_name, username)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            first_name = excluded.first_name,
            username = excluded.username
    """, (user.id, first_name, username))
    db.commit()


def get_user_channels(user_id):
    cursor.execute("""
        SELECT id, channel FROM user_channels
        WHERE user_id = ?
        ORDER BY id ASC
    """, (user_id,))
    return cursor.fetchall()


def get_user_channel(user_id):
    channels = get_user_channels(user_id)
    return channels[0][1] if channels else None


def save_user_channel(user_id, channel):
    cursor.execute("""
        INSERT OR IGNORE INTO user_channels (user_id, channel)
        VALUES (?, ?)
    """, (user_id, channel))
    # Eski ustun ham saqlanadi — eski funksiyalar bilan moslik uchun.
    cursor.execute("UPDATE users SET channel = ? WHERE user_id = ?", (channel, user_id))
    if cursor.rowcount == 0:
        cursor.execute("INSERT OR IGNORE INTO users (user_id, channel) VALUES (?, ?)", (user_id, channel))
    db.commit()


def delete_user_channel(user_id, channel_id):
    cursor.execute("DELETE FROM user_channels WHERE id = ? AND user_id = ?", (channel_id, user_id))
    db.commit()
    return cursor.rowcount > 0

def save_sticker(category, file_id):
    cursor.execute("""
        INSERT INTO stickers (category, file_id)
        VALUES (?, ?)
    """, (category, file_id))

    db.commit()


def get_stickers(category):
    cursor.execute("""
        SELECT file_id
        FROM stickers
        WHERE category = ?
    """, (category,))

    return [
        row[0]
        for row in cursor.fetchall()
    ]


def get_all_stickers():
    cursor.execute("""
        SELECT file_id
        FROM stickers
    """)

    return [
        row[0]
        for row in cursor.fetchall()
    ]


def record_ai_usage(user_id):
    cursor.execute("""
        INSERT INTO ai_usage (user_id, request_count)
        VALUES (?, 1)
        ON CONFLICT(user_id)
        DO UPDATE SET request_count = request_count + 1
    """, (user_id,))
    db.commit()


# =========================================================
# START
# =========================================================

@dp.message(Command("start"))
async def start_handler(
    message: types.Message,
    state: FSMContext
):

    register_user(message.from_user)
    await state.clear()

    channels = get_user_channels(message.from_user.id)

    if channels:
        lines = ["👋 <b>Manager BOT</b>", "", "📢 <b>Ulangan kanallar:</b>"]
        for i, (_, ch) in enumerate(channels, 1):
            lines.append(f"{i}. <code>{html.escape(ch)}</code>")
        lines += ["", "➕ Yangi kanal qo'shish: /channels", "📅 Rejalashtirilgan postlar: /posts"]
        await message.answer("\n".join(lines))
        return

    await message.answer(
        "👋 <b>Manager BOT</b>\n\n"
        "Avval kanal ulang. Bir nechta kanalni ham ulashingiz mumkin.\n\n"
        "📢 Kanal username'sini yuboring:\n"
        "<code>@kanal_username</code>"
    )
    await state.set_state(SetupState.waiting_channel)


# =========================================================
# CHANNEL CONNECT
# =========================================================

async def check_channel_admin(
    user_id,
    channel
):

    try:

        user_member = await bot.get_chat_member(
            channel,
            user_id
        )

        if user_member.status not in [
            "administrator",
            "creator"
        ]:
            return False, "Siz bu kanalda admin emassiz."



        bot_member = await bot.get_chat_member(
            channel,
            (await bot.me()).id
        )

        if bot_member.status not in [
            "administrator",
            "creator"
        ]:
            return False, (
                "Bot kanalga admin qilinmagan.\n\n"
                "Avval botni kanalga administrator qilib qo'shing."
            )


        return True, "OK"


    except Exception as e:

        return False, (
            "Kanalni tekshirib bo'lmadi.\n\n"
            "Kanal username'si to'g'ri ekanini "
            "va bot kanalga admin qilinganini tekshiring."
        )


@dp.message(SetupState.waiting_channel)
async def receive_channel(
    message: types.Message,
    state: FSMContext
):

    channel = message.text.strip()

    if not channel.startswith("@"):
        await message.answer(
            "❌ Kanal username <code>@</code> bilan boshlanishi kerak.\n\n"
            "Masalan:\n"
            "<code>@mychannel</code>"
        )
        return


    ok, result = await check_channel_admin(
        message.from_user.id,
        channel
    )


    if not ok:

        await message.answer(
            f"❌ <b>{result}</b>"
        )

        return


    await state.update_data(
        channel=channel
    )

    await message.answer(
        f"📢 Kanal: <code>{channel}</code>\n\n"
        "Kanalni ulashni tasdiqlaysizmi?\n\n"
        "Tasdiqlash uchun:\n"
        "<code>TASDIQLASH</code>"
    )

    await state.set_state(
        SetupState.waiting_confirmation
    )


# =========================================================
# CONFIRM CHANNEL
# =========================================================

@dp.message(SetupState.waiting_confirmation)
async def confirm_channel(
    message: types.Message,
    state: FSMContext
):

    if message.text.strip().upper() != "TASDIQLASH":

        await message.answer(
            "❌ Tasdiqlash uchun aynan:\n"
            "<code>TASDIQLASH</code>\n"
            "deb yozing."
        )

        return


    data = await state.get_data()

    channel = data.get("channel")

    save_user_channel(
        message.from_user.id,
        channel
    )

    await state.clear()


    await message.answer(
        "✅ <b>Kanal muvaffaqiyatli ulandi!</b>\n\n"
        f"📢 <code>{channel}</code>\n\n"
        "Endi post yuboring.\n"
        "Masalan, matn yoki rasm + caption."
    )


# =========================================================
# MULTI-CHANNEL MANAGEMENT
# =========================================================


def channel_manage_keyboard(user_id):
    rows = []
    for channel_id, channel in get_user_channels(user_id):
        rows.append([InlineKeyboardButton(text=f"📢 {channel}", callback_data=f"select_channel:{channel_id}")])
    rows.append([InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_channel")])
    if get_user_channels(user_id):
        rows.append([InlineKeyboardButton(text="🗑 Kanal o'chirish", callback_data="delete_channel_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def channel_select_keyboard(user_id):
    rows = []
    for channel_id, channel in get_user_channels(user_id):
        rows.append([InlineKeyboardButton(text=f"📢 {channel}", callback_data=f"select_channel:{channel_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command("channels"))
async def channels_handler(message: types.Message, state: FSMContext):
    register_user(message.from_user)
    await state.clear()
    channels = get_user_channels(message.from_user.id)
    if not channels:
        await message.answer("📭 Hali kanal ulanmagan.\n\n➕ Kanal qo'shish uchun <code>@kanal_username</code> yuboring.")
        await state.set_state(SetupState.waiting_channel)
        return
    text = "📢 <b>Mening kanallarim</b>\n\n" + "\n".join(
        f"{i}. <code>{html.escape(ch)}</code>" for i, (_, ch) in enumerate(channels, 1)
    )
    await message.answer(text + "\n\n➕ Yangi kanal qo'shish yoki 🗑 o'chirish uchun tugmalardan foydalaning.", reply_markup=channel_manage_keyboard(message.from_user.id))


@dp.callback_query(F.data == "add_channel")
async def add_channel_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(SetupState.waiting_channel)
    await callback.message.answer("➕ <b>Yangi kanal qo'shish</b>\n\nKanal username'sini yuboring:\n<code>@kanal_username</code>")
    await callback.answer()


@dp.callback_query(F.data == "delete_channel_menu")
async def delete_channel_menu(callback: types.CallbackQuery, state: FSMContext):
    channels = get_user_channels(callback.from_user.id)
    if not channels:
        await callback.answer("Kanal yo'q", show_alert=True)
        return
    rows = [[InlineKeyboardButton(text=f"🗑 {ch}", callback_data=f"remove_channel:{cid}")] for cid, ch in channels]
    rows.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="channel_menu")])
    await callback.message.answer("🗑 <b>Qaysi kanalni o'chiramiz?</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@dp.callback_query(F.data.startswith("remove_channel:"))
async def remove_channel_callback(callback: types.CallbackQuery):
    try:
        channel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("❌ Xato", show_alert=True)
        return
    cursor.execute("SELECT channel FROM user_channels WHERE id = ? AND user_id = ?", (channel_id, callback.from_user.id))
    row = cursor.fetchone()
    if not row:
        await callback.answer("❌ Kanal topilmadi", show_alert=True)
        return
    channel = row[0]
    cursor.execute("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = ? AND channel = ? AND status = 'pending'", (callback.from_user.id, channel))
    pending = cursor.fetchone()[0]
    if pending:
        await callback.answer(f"❌ Bu kanalda {pending} ta rejalashtirilgan post bor. Avval /posts orqali ularni o'chiring.", show_alert=True)
        return
    delete_user_channel(callback.from_user.id, channel_id)
    await callback.message.answer(f"🗑 <b>{html.escape(channel)}</b> kanali o'chirildi.")
    await callback.answer("Kanal o'chirildi")


@dp.callback_query(F.data == "channel_menu")
async def channel_menu_callback(callback: types.CallbackQuery):
    await callback.message.answer("📢 <b>Mening kanallarim</b>", reply_markup=channel_manage_keyboard(callback.from_user.id))
    await callback.answer()


@dp.callback_query(F.data.startswith("select_channel:"))
async def select_channel_callback(callback: types.CallbackQuery, state: FSMContext):
    try:
        channel_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("❌ Xato", show_alert=True)
        return
    cursor.execute("SELECT channel FROM user_channels WHERE id = ? AND user_id = ?", (channel_id, callback.from_user.id))
    row = cursor.fetchone()
    if not row:
        await callback.answer("❌ Kanal topilmadi", show_alert=True)
        return
    channel = row[0]
    data = await state.get_data()
    if not data.get("post_message_id"):
        await callback.answer("Kanal tanlandi")
        return
    await state.update_data(selected_channel=channel)
    await state.set_state(SetupState.waiting_time)
    await callback.message.answer(f"✅ Kanal tanlandi: <code>{html.escape(channel)}</code>\n\n⏰ Qachon yuborilsin?\nMasalan: <code>ertaga 18:30</code>")
    await callback.answer()


# =========================================================
# STICKER CATEGORY
# =========================================================

def choose_sticker_category(text):

    text = (text or "").lower()


    categories = {

        "salom": [
            "salom",
            "assalom",
            "hello",
            "hayrli"
        ],

        "sport": [
            "futbol",
            "sport",
            "match",
            "gol",
            "jamoa",
            "basketbol",
            "voleybol"
        ],

        "kulgi": [
            "kulgi",
            "hazil",
            "haha",
            "😂",
            "🤣"
        ],

        "sevgi": [
            "sevgi",
            "love",
            "❤️",
            "yurak"
        ],

        "bayram": [
            "bayram",
            "navruz",
            "yangi yil",
            "tug'ilgan kun",
            "tabrik"
        ],

        "muhim": [
            "muhim",
            "diqqat",
            "e'lon",
            "ogohlantirish"
        ],

        "oqish": [
            "dars",
            "maktab",
            "imtihon",
            "o'qish",
            "kitob",
            "ta'lim"
        ],

        "it": [
            "python",
            "c++",
            "java",
            "html",
            "css",
            "javascript",
            "programming",
            "dastur",
            "kod",
            "developer"
        ],

        "muvaffaqiyat": [
            "g'alaba",
            "muvaffaqiyat",
            "yutdim",
            "tabriklayman",
            "zo'r"
        ],

        "xafa": [
            "xafa",
            "afsus",
            "yomon",
            "😔",
            "😢"
        ]
    }


    for category, words in categories.items():

        for word in words:

            if word in text:
                return category


    return "default"


def get_matching_sticker(category):

    stickers = get_stickers(category)

    if stickers:
        return random.choice(stickers)


    all_stickers = get_all_stickers()

    if all_stickers:
        return random.choice(all_stickers)


    return None


# =========================================================
# AI ASSISTANT
# =========================================================

async def ask_ai(prompt: str) -> str:
    # AI ga O‘zbekiston (Toshkent) vaqti bo‘yicha aniq joriy sana-vaqtni beramiz.
    # Shunda "bugun qaysi kun?", "ertaga qaysi sana?" kabi savollarda
    # model eski yoki noto‘g‘ri sanani taxmin qilmaydi.
    now = datetime.now(TZ)
    current_datetime = now.strftime("%Y-%m-%d %H:%M:%S")
    current_date = now.strftime("%Y-%m-%d")

    response = await ai_client.responses.create(
        model=AI_MODEL,
        instructions=(
            "You are the AI assistant inside Manager BOT. "
            "Answer clearly and briefly in Uzbek unless the user asks for another language. "
            "Help with Telegram channel posts, writing, ideas, translation, programming, "
            "and general safe questions. "
            f"IMPORTANT: The current date and time in Tashkent, Uzbekistan is "
            f"{current_datetime} (UTC+05:00), and today's date is {current_date}. "
            "For questions about today, tomorrow, yesterday, day of week, or current date/time, "
            "use this provided Tashkent date/time as the source of truth. "
            "Do not guess or use an older date."
        ),
        input=prompt,
    )

    text = (response.output_text or "").strip()

    if not text:
        return "❌ AI javob qaytarmadi."

    return text


@dp.message(Command("ai"))
async def ai_handler(message: types.Message):
    register_user(message.from_user)
    prompt = (message.text or "").partition(" ")[2].strip()

    if not prompt:
        await message.answer(
            "🤖 <b>AI yordamchi</b>\n\n"
            "Savolingizni /ai dan keyin yozing.\n\n"
            "Masalan:\n"
            "<code>/ai Telegram kanal uchun motivatsion post yoz</code>\n"
            "<code>/ai Python'da list nima?</code>"
        )
        return

    await message.answer("🤖 AI o'ylayapti...")

    try:
        record_ai_usage(message.from_user.id)
        answer = await ask_ai(prompt)
        await message.answer(html.escape(answer))
    except Exception as e:
        print("OpenAI xatosi:", e)
        await message.answer(
            "❌ AI bilan bog'lanishda xatolik yuz berdi. "
            "Render Logs bo'limini tekshiring."
        )


@dp.message(Command("aipost"))
async def ai_post_handler(message: types.Message):
    register_user(message.from_user)
    prompt = (message.text or "").partition(" ")[2].strip()

    if not prompt:
        await message.answer(
            "📝 <b>AI Post</b>\n\n"
            "Qanday post kerakligini yozing.\n\n"
            "Masalan:\n"
            "<code>/aipost Bugun dasturlash haqida motivatsion post</code>"
        )
        return

    await message.answer("📝 AI post tayyorlayapti...")

    try:
        record_ai_usage(message.from_user.id)
        answer = await ask_ai(
            "Telegram kanal uchun tayyor post yoz. "
            "Ortiqcha izohsiz, faqat post matnini ber. "
            f"Mavzu: {prompt}"
        )
        await message.answer(
            "✅ <b>AI tayyorlagan post:</b>\n\n" + html.escape(answer)
        )
    except Exception as e:
        print("OpenAI post xatosi:", e)
        await message.answer(
            "❌ AI post yaratishda xatolik yuz berdi. "
            "Render Logs bo'limini tekshiring."
        )


# =========================================================
# EXTRA FEATURES
# =========================================================

def preview_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data="preview_confirm"),
        InlineKeyboardButton(text="❌ Bekor qilish", callback_data="preview_cancel")
    ]])


def repeat_keyboard(post_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Har kuni", callback_data=f"repeat:daily:{post_id}"),
         InlineKeyboardButton(text="📆 Har hafta", callback_data=f"repeat:weekly:{post_id}")],
        [InlineKeyboardButton(text="❌ Bekor", callback_data="repeat_cancel")]
    ])


def template_text(kind):
    templates = {
        "reklama": "🔥 <b>REKLAMA</b>\n\nMahsulot/xizmat: [nomi]\n💰 Narx: [narx]\n📩 Murojaat: [aloqa]\n\n#reklama",
        "yangilik": "📰 <b>YANGILIK</b>\n\n[Yangilik matni]\n\n#yangilik",
        "elon": "📢 <b>E'LON</b>\n\n[Muhim ma'lumot]\n🕐 Vaqt: [vaqt]\n📍 Manzil: [manzil]",
        "motivatsiya": "💪 <b>MOTIVATSIYA</b>\n\n[Motivatsion fikr]\n\n#motivatsiya"
    }
    return templates.get(kind)


@dp.message(Command("templates"))
async def templates_handler(message: types.Message):
    await message.answer(
        "📝 <b>Post shablonlari</b>\n\n"
        "<code>/template reklama</code>\n"
        "<code>/template yangilik</code>\n"
        "<code>/template elon</code>\n"
        "<code>/template motivatsiya</code>"
    )


@dp.message(Command("template"))
async def template_handler(message: types.Message):
    kind = (message.text or "").partition(" ")[2].strip().lower()
    text = template_text(kind)
    if not text:
        await message.answer("❌ Shablon topilmadi. /templates ni bosing.")
        return
    await message.answer(text)


@dp.message(Command("improve"))
async def improve_handler(message: types.Message):
    prompt = (message.text or "").partition(" ")[2].strip()
    if not prompt:
        await message.answer("✨ <b>AI postni yaxshilash</b>\n\nMasalan: <code>/improve Bugun yangi kursimiz boshlandi...</code>")
        return
    try:
        record_ai_usage(message.from_user.id)
        answer = await ask_ai("Quyidagi Telegram postini mazmunini saqlagan holda chiroyli, xatosiz, o'qilishi oson qilib formatla. Sarlavha, mos emoji va kerak bo'lsa 2-4 hashtag qo'sh. Faqat tayyor postni qaytar.\n\n" + prompt)
        await message.answer("✨ <b>Yaxshilangan post:</b>\n\n" + html.escape(answer))
    except Exception as e:
        print("Improve xatosi:", e)
        await message.answer("❌ AI postni yaxshilay olmadi.")


@dp.message(Command("caption"))
async def caption_handler(message: types.Message):
    prompt = (message.text or "").partition(" ")[2].strip()
    if not prompt:
        await message.answer("🖼️ <b>AI caption</b>\n\nMasalan: <code>/caption Yangi futbol formasi reklamasi</code>")
        return
    try:
        record_ai_usage(message.from_user.id)
        answer = await ask_ai("Telegram uchun qisqa va qiziqarli caption yoz. 1-3 emoji va 2-4 hashtag qo'sh. Faqat captionni qaytar. Mavzu: " + prompt)
        await message.answer("🖼️ <b>Caption:</b>\n\n" + html.escape(answer))
    except Exception as e:
        print("Caption xatosi:", e)
        await message.answer("❌ Caption yaratishda xatolik.")


@dp.message(Command("history"))
async def history_handler(message: types.Message):
    rows = cursor.execute("SELECT id, channel, send_time, status FROM scheduled_posts WHERE user_id = ? AND status != 'pending' ORDER BY id DESC LIMIT 20", (message.from_user.id,)).fetchall()
    if not rows:
        await message.answer("📭 Hali postlar tarixi yo'q.")
        return
    lines = ["📜 <b>Postlar tarixi</b>", ""]
    for pid, channel, send_time, status in rows:
        try: t = datetime.fromisoformat(send_time).astimezone(TZ).strftime("%d.%m %H:%M")
        except Exception: t = send_time
        icon = {"sent":"✅", "error":"❌", "cancelled":"🗑", "expired":"⌛"}.get(status, "•")
        lines.append(f"{icon} #{pid} — <code>{html.escape(channel)}</code> — {t} — {status}")
    await message.answer("\n".join(lines))


@dp.message(Command("admins"))
async def admins_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Faqat admin uchun.")
        return
    rows = cursor.execute("SELECT user_id FROM bot_admins ORDER BY user_id").fetchall()
    text = "👑 <b>Qo'shimcha adminlar</b>\n\n" + ("\n".join(f"• <code>{r[0]}</code>" for r in rows) if rows else "Hozircha yo'q")
    text += "\n\n➕ Qo'shish: <code>/adminadd USER_ID</code>\n🗑 O'chirish: <code>/admindel USER_ID</code>"
    await message.answer(text)


@dp.message(Command("adminadd"))
async def adminadd_handler(message: types.Message):
    if not (ADMIN_USER_ID == message.from_user.id):
        await message.answer("❌ Faqat bot egasi yangi admin qo'sha oladi.")
        return
    arg = (message.text or "").partition(" ")[2].strip()
    try: uid = int(arg)
    except ValueError:
        await message.answer("❌ Masalan: <code>/adminadd 123456789</code>")
        return
    cursor.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (uid,)); db.commit()
    await message.answer(f"✅ <code>{uid}</code> admin qilindi.")


@dp.message(Command("admindel"))
async def admindel_handler(message: types.Message):
    if ADMIN_USER_ID != message.from_user.id:
        await message.answer("❌ Faqat bot egasi adminni o'chira oladi.")
        return
    arg = (message.text or "").partition(" ")[2].strip()
    try: uid = int(arg)
    except ValueError:
        await message.answer("❌ Masalan: <code>/admindel 123456789</code>")
        return
    cursor.execute("DELETE FROM bot_admins WHERE user_id = ?", (uid,)); db.commit()
    await message.answer(f"🗑 <code>{uid}</code> adminlikdan olindi.")


@dp.message(Command("channelstats"))
async def channel_stats_handler(message: types.Message):
    channels = get_user_channels(message.from_user.id)
    if not channels:
        await message.answer("❌ Avval kanal ulang.")
        return
    lines = ["📊 <b>Kanal statistikasi</b>", ""]
    for _, channel in channels:
        try:
            members = await bot.get_chat_member_count(channel)
            err = ""
        except Exception:
            members = "?"; err = " (bot admin huquqini tekshiring)"
        pending = cursor.execute("SELECT COUNT(*) FROM scheduled_posts WHERE user_id=? AND channel=? AND status='pending'", (message.from_user.id, channel)).fetchone()[0]
        sent = cursor.execute("SELECT COUNT(*) FROM scheduled_posts WHERE user_id=? AND channel=? AND status='sent'", (message.from_user.id, channel)).fetchone()[0]
        lines.append(f"📢 <code>{html.escape(channel)}</code>{err}\n👥 Obunachilar: <b>{members}</b>\n⏰ Kutilayotgan: <b>{pending}</b>\n✅ Yuborilgan: <b>{sent}</b>\n")
    await message.answer("\n".join(lines))


@dp.callback_query(F.data == "preview_cancel")
async def preview_cancel_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ Post rejalashtirish bekor qilindi.")
    await callback.answer()


@dp.callback_query(F.data == "preview_confirm")
async def preview_confirm_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("preview_target"):
        await callback.answer("❌ Preview ma'lumoti topilmadi.", show_alert=True); return
    target = datetime.fromisoformat(data["preview_target"])
    cursor.execute("""INSERT INTO scheduled_posts (user_id, from_chat_id, message_id, channel, send_time, sticker_category, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')""", (callback.from_user.id, data["post_chat_id"], data["post_message_id"], data["selected_channel"], target.isoformat(), data.get("sticker_category","default")))
    db.commit(); post_id = cursor.lastrowid
    scheduler.add_job(send_scheduled_post, trigger=DateTrigger(run_date=target), args=[post_id], id=f"post_{post_id}", replace_existing=True)
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ <b>Post rejalashtirildi!</b>\n\n📢 <code>{html.escape(data['selected_channel'])}</code>\n⏰ <code>{target.strftime('%d.%m.%Y %H:%M')}</code>\n\n📅 /posts")
    await callback.answer("Tasdiqlandi")


@dp.callback_query(F.data.startswith("repeat_menu:"))
async def repeat_menu_callback(callback: types.CallbackQuery):
    post_id = int(callback.data.split(":",1)[1])
    if not get_pending_post(post_id, callback.from_user.id):
        await callback.answer("❌ Post topilmadi.", show_alert=True); return
    await callback.message.answer("🔁 Qanchada bir takrorlansin?", reply_markup=repeat_keyboard(post_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("repeat:"))
async def repeat_callback(callback: types.CallbackQuery):
    try: _, interval, post_id = callback.data.split(":")
    except ValueError:
        await callback.answer("❌ Xato", show_alert=True); return
    row = get_pending_post(int(post_id), callback.from_user.id)
    if not row:
        await callback.answer("❌ Post topilmadi.", show_alert=True); return
    next_time = datetime.now(TZ) + (timedelta(days=1) if interval == "daily" else timedelta(days=7))
    cursor.execute("INSERT INTO repeating_posts (user_id, from_chat_id, message_id, channel, interval_type, next_time, sticker_category) VALUES (?, ?, ?, ?, ?, ?, ?)", (callback.from_user.id, row[1], row[2], row[3], interval, next_time.isoformat(), row[5]))
    db.commit(); rid = cursor.lastrowid
    scheduler.add_job(send_repeating_post, trigger=IntervalTrigger(days=1 if interval == 'daily' else 7, start_date=next_time), args=[rid], id=f"repeat_{rid}", replace_existing=True)
    await callback.message.answer(f"🔁 Takroriy post yoqildi: <b>{'har kuni' if interval == 'daily' else 'har hafta'}</b>.")
    await callback.answer()


@dp.callback_query(F.data == "repeat_cancel")
async def repeat_cancel_callback(callback: types.CallbackQuery):
    await callback.answer("Bekor qilindi")


async def send_repeating_post(repeat_id):
    row = cursor.execute("SELECT user_id, from_chat_id, message_id, channel, interval_type, sticker_category FROM repeating_posts WHERE id=? AND status='active'", (repeat_id,)).fetchone()
    if not row: return
    user_id, from_chat_id, message_id, channel, interval, sticker_category = row
    try:
        await bot.copy_message(chat_id=channel, from_chat_id=from_chat_id, message_id=message_id)
        sticker = get_matching_sticker(sticker_category)
        if sticker: await bot.send_sticker(chat_id=channel, sticker=sticker)
        cursor.execute("UPDATE repeating_posts SET next_time=? WHERE id=?", ((datetime.now(TZ)+timedelta(days=1 if interval=='daily' else 7)).isoformat(), repeat_id)); db.commit()
    except Exception as e:
        print("Repeat post xatosi:", e)
        try: await bot.send_message(user_id, f"⚠️ Takroriy post yuborilmadi: <code>{html.escape(str(e)[:300])}</code>")
        except Exception: pass


async def restore_repeating_posts():
    rows = cursor.execute("SELECT id, next_time, interval_type FROM repeating_posts WHERE status='active'").fetchall()
    for rid, next_time, interval in rows:
        try:
            target = datetime.fromisoformat(next_time)
            if target <= datetime.now(TZ): target = datetime.now(TZ) + timedelta(minutes=1)
            scheduler.add_job(send_repeating_post, trigger=IntervalTrigger(days=1 if interval=='daily' else 7, start_date=target), args=[rid], id=f"repeat_{rid}", replace_existing=True)
        except Exception as e: print("Repeat restore xatosi:", e)


# =========================================================
# ADMIN STATISTICS
# =========================================================

def is_admin(user_id):
    if ADMIN_USER_ID != 0 and user_id == ADMIN_USER_ID:
        return True
    cursor.execute("SELECT 1 FROM bot_admins WHERE user_id = ?", (user_id,))
    return cursor.fetchone() is not None


@dp.message(Command("adminstats"))
async def admin_stats_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bu komanda faqat bot egasi uchun.")
        return

    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM user_channels")
    channels_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM scheduled_posts
        WHERE status = 'pending'
    """)
    pending_posts = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(request_count), 0) FROM ai_usage")
    ai_requests = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM stickers")
    stickers_count = cursor.fetchone()[0]

    await message.answer(
        "📊 <b>Manager BOT statistikasi</b>\n\n"
        f"👤 Foydalanuvchilar: <b>{users_count}</b> ta\n"
        f"📢 Ulangan kanallar: <b>{channels_count}</b> ta\n"
        f"📝 Kutilayotgan postlar: <b>{pending_posts}</b> ta\n"
        f"🤖 AI so'rovlari: <b>{ai_requests}</b> ta\n"
        f"🎨 Saqlangan stickerlar: <b>{stickers_count}</b> ta"
    )


# =========================================================
# USER LIST (ADMIN ONLY)
# =========================================================

@dp.message(Command("users"))
async def users_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bu komanda faqat bot egasi uchun.")
        return

    cursor.execute("""
        SELECT first_name, username
        FROM users
        ORDER BY user_id ASC
    """)
    rows = cursor.fetchall()

    if not rows:
        await message.answer("👥 Hozircha botdan foydalanganlar yo'q.")
        return

    lines = [f"👥 <b>Bot foydalanuvchilari: {len(rows)} ta</b>", ""]

    for index, (first_name, username) in enumerate(rows, 1):
        name = html.escape(first_name or "Noma'lum")
        username_text = f"@{html.escape(username)}" if username else "username yo'q"
        lines.append(f"{index}. 👤 <b>{name}</b> — {username_text}")

    await message.answer("\n".join(lines))


# =========================================================
# SCHEDULED POSTS MANAGEMENT
# =========================================================

def scheduled_posts_keyboard(post_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Edit",
                    callback_data=f"edit_post:{post_id}"
                ),
                InlineKeyboardButton(
                    text="🗑 O'chirish",
                    callback_data=f"delete_post:{post_id}"
                )
            ]
        ]
    )


def get_pending_post(post_id, user_id):
    cursor.execute("""
        SELECT id, from_chat_id, message_id, channel, send_time, sticker_category
        FROM scheduled_posts
        WHERE id = ? AND user_id = ? AND status = 'pending'
    """, (post_id, user_id))
    return cursor.fetchone()


def format_scheduled_post(row):
    post_id, from_chat_id, message_id, channel, send_time, sticker_category = row
    try:
        target = datetime.fromisoformat(send_time).astimezone(TZ)
        time_text = target.strftime("%d.%m.%Y %H:%M")
    except Exception:
        time_text = send_time

    return (
        f"📝 <b>Post #{post_id}</b>\n"
        f"📢 Kanal: <code>{html.escape(channel)}</code>\n"
        f"⏰ Vaqt: <code>{time_text}</code>\n"
        f"🎨 Sticker: <code>{html.escape(sticker_category or 'default')}</code>"
    )


@dp.message(Command("posts"))
async def scheduled_posts_handler(message: types.Message):
    register_user(message.from_user)
    user_id = message.from_user.id

    cursor.execute("""
        SELECT id, from_chat_id, message_id, channel, send_time, sticker_category
        FROM scheduled_posts
        WHERE user_id = ? AND status = 'pending'
        ORDER BY send_time ASC
    """, (user_id,))

    rows = cursor.fetchall()

    if not rows:
        await message.answer(
            "📭 <b>Rejalashtirilgan postlar yo'q.</b>\n\n"
            "Yangi post yuborib, vaqt belgilang."
        )
        return

    await message.answer(
        f"📅 <b>Rejalashtirilgan postlar: {len(rows)} ta</b>\n\n"
        "✏️ Edit — postni almashtirish\n"
        "🗑 O'chirish — reja va scheduler'dan olib tashlash"
    )

    for row in rows:
        await message.answer(
            format_scheduled_post(row),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Edit", callback_data=f"edit_post:{row[0]}"), InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"delete_post:{row[0]}")],
                [InlineKeyboardButton(text="🔁 Takrorlash", callback_data=f"repeat_menu:{row[0]}")]
            ])
        )


@dp.callback_query(F.data.startswith("edit_post:"))
async def edit_post_callback(callback: types.CallbackQuery, state: FSMContext):
    try:
        post_id = int(callback.data.split(":", 1)[1])
    except (ValueError, AttributeError):
        await callback.answer("❌ Noto'g'ri post.", show_alert=True)
        return

    row = get_pending_post(post_id, callback.from_user.id)

    if not row:
        await callback.answer("❌ Bu post topilmadi yoki allaqachon yuborilgan.", show_alert=True)
        return

    await state.clear()
    await state.update_data(edit_post_id=post_id)
    await state.set_state(EditPostState.waiting_replacement)

    await callback.message.answer(
        f"✏️ <b>Post #{post_id} ni tahrirlash</b>\n\n"
        "Endi yangi variantni yuboring.\n"
        "Matn, rasm, video yoki boshqa postni yuborishingiz mumkin.\n\n"
        "❌ Bekor qilish: <code>/cancel</code>"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("delete_post:"))
async def delete_post_callback(callback: types.CallbackQuery):
    try:
        post_id = int(callback.data.split(":", 1)[1])
    except (ValueError, AttributeError):
        await callback.answer("❌ Noto'g'ri post.", show_alert=True)
        return

    row = get_pending_post(post_id, callback.from_user.id)

    if not row:
        await callback.answer("❌ Bu post topilmadi yoki allaqachon yuborilgan.", show_alert=True)
        return

    try:
        scheduler.remove_job(f"post_{post_id}")
    except Exception:
        pass

    cursor.execute("""
        UPDATE scheduled_posts
        SET status = 'cancelled'
        WHERE id = ? AND user_id = ? AND status = 'pending'
    """, (post_id, callback.from_user.id))
    db.commit()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"🗑 <b>Post #{post_id} o'chirildi.</b>\n\n"
        "U endi belgilangan vaqtda kanalga yuborilmaydi."
    )
    await callback.answer("Post o'chirildi")


@dp.message(Command("cancel"))
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == EditPostState.waiting_replacement.state:
        await state.clear()
        await message.answer("❌ Tahrirlash bekor qilindi.")
        return
    if current_state in (PreviewState.waiting_confirmation.state, SetupState.waiting_time.state, StickerState.waiting_category.state, StickerState.waiting_sticker.state):
        await state.clear()
        await message.answer("❌ Joriy amal bekor qilindi.")
        return
    await message.answer("ℹ️ Hozir bekor qilinadigan amal yo'q.")


@dp.message(EditPostState.waiting_replacement)
async def receive_edit_replacement(message: types.Message, state: FSMContext):
    data = await state.get_data()
    post_id = data.get("edit_post_id")

    if not post_id:
        await state.clear()
        await message.answer("❌ Tahrirlash ma'lumoti topilmadi.")
        return

    row = get_pending_post(post_id, message.from_user.id)

    if not row:
        await state.clear()
        await message.answer("❌ Bu post allaqachon yuborilgan yoki o'chirilgan.")
        return

    # Yangi yuborilgan xabarni scheduled postning manbasi qilib qo'yamiz.
    # Shuning uchun matn, rasm, video va boshqa Telegram post turlari bilan ishlaydi.
    replacement_text = message.text or message.caption or ""
    new_category = choose_sticker_category(replacement_text)

    cursor.execute("""
        UPDATE scheduled_posts
        SET from_chat_id = ?, message_id = ?, sticker_category = ?
        WHERE id = ? AND user_id = ? AND status = 'pending'
    """, (
        message.chat.id,
        message.message_id,
        new_category,
        post_id,
        message.from_user.id
    ))
    db.commit()

    await state.clear()

    updated = get_pending_post(post_id, message.from_user.id)
    if updated:
        await message.answer(
            "✅ <b>Post yangilandi!</b>\n\n" +
            format_scheduled_post(updated) +
            "\n\nEski variant o'rniga yangi variant belgilangan vaqtda yuboriladi."
        )
    else:
        await message.answer("✅ Post yangilandi!")


# =========================================================
# SAVE POST
# =========================================================

@dp.message()
async def all_messages(
    message: types.Message,
    state: FSMContext
):

    register_user(message.from_user)
    current_state = await state.get_state()

    # Commandlar o'zining handlerlarida ishlaydi.
    if message.text and message.text.startswith("/"):
        return

    # -----------------------------------------------------
    # CHANNEL STATE
    # -----------------------------------------------------

    if current_state == SetupState.waiting_channel.state:
        await receive_channel(message, state)
        return


    if current_state == SetupState.waiting_confirmation.state:
        await confirm_channel(message, state)
        return


    # -----------------------------------------------------
    # TIME STATE
    # -----------------------------------------------------

    if current_state == SetupState.waiting_time.state:

        await process_time(
            message,
            state
        )

        return


    if current_state == PreviewState.waiting_confirmation.state:
        await message.answer("👀 Avval previewdagi <b>✅ Tasdiqlash</b> yoki <b>❌ Bekor qilish</b> tugmasini bosing.")
        return


    # -----------------------------------------------------
    # STICKER STATE
    # -----------------------------------------------------

    if current_state == StickerState.waiting_category.state:

        await receive_sticker_category(
            message,
            state
        )

        return


    if current_state == StickerState.waiting_sticker.state:

        await receive_sticker(
            message,
            state
        )

        return


    # -----------------------------------------------------
    # NORMAL POST
    # -----------------------------------------------------

    channels = get_user_channels(message.from_user.id)

    if not channels:
        await message.answer(
            "❌ Avval kanalni ulang.\n\n"
            "/channels"
        )
        return

    # Matnni aniqlaymiz
    post_text = message.text or message.caption or ""

    category = choose_sticker_category(
        post_text
    )


    # Vaqtni kutamiz
    await state.update_data(
        post_chat_id=message.chat.id,
        post_message_id=message.message_id,
        sticker_category=category
    )

    if len(channels) > 1:
        await message.answer(
            "📥 <b>POST QABUL QILINDI</b>\n\n"
            "📢 Qaysi kanalga yuborilsin? Tanlang:",
            reply_markup=channel_select_keyboard(message.from_user.id)
        )
        return

    channel = channels[0][1]
    await state.update_data(selected_channel=channel)
    await message.answer(
        "📥 <b>POST QABUL QILINDI</b>\n\n"
        f"📢 Kanal: <code>{html.escape(channel)}</code>\n"
        f"🎨 Sticker kategoriyasi: <code>{category}</code>\n\n"
        "⏰ Qachon yuborilsin?\n\n"
        "Masalan:\n"
        "<code>ertaga 18:30</code>\n"
        "<code>20-09 15:00</code>"
    )
    await state.set_state(SetupState.waiting_time)


# =========================================================
# TIME PARSER
# =========================================================

MONTHS = {

    "yanvar": 1,
    "fevral": 2,
    "mart": 3,
    "aprel": 4,
    "may": 5,
    "iyun": 6,
    "iyul": 7,
    "avgust": 8,
    "sentabr": 9,
    "sentyabr": 9,
    "oktabr": 10,
    "noyabr": 11,
    "dekabr": 12
}


def parse_time(text):
    text = (text or '').strip().lower().replace(',', ':')
    now = datetime.now(TZ)
    parts = text.split()
    import re
    def hm(v):
        m = re.fullmatch(r'(\d{1,2})(?::|\.|\s)(\d{2})', v.strip())
        if not m: return None
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59: return None
        return h, mi
    # 18:30 / 18.30 / 18 30
    m = re.fullmatch(r'(\d{1,2})(?::|\.)(\d{2})', text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h <= 23 and mi <= 59: return datetime(now.year, now.month, now.day, h, mi, tzinfo=TZ)
    # 18:30 ertaga / ertaga 18:30 / 18.30 ertaga
    if len(parts)==2:
        a,b=parts
        t=hm(a) or hm(b)
        dayword = b if t==hm(a) else a
        if t and dayword in ('bugun','today','ertaga','tomorrow'):
            d=now.date() + timedelta(days=1 if dayword in ('ertaga','tomorrow') else 0)
            return datetime(d.year,d.month,d.day,t[0],t[1],tzinfo=TZ)
        # 20-09 15:00 / 15:00 20-09
        datepart = a if hm(b) else b
        timepart = b if hm(b) else a
        tm=hm(timepart)
        try:
            day,month=map(int,re.split(r'[-./]',datepart));
            if tm and 1<=month<=12 and 1<=day<=31: return datetime(now.year,month,day,tm[0],tm[1],tzinfo=TZ)
        except Exception: pass
    # 20 sentabr 15:00 / 15:00 20 sentabr
    if len(parts)==3:
        if parts[1] in MONTHS:
            day,mon,timepart=parts[0],parts[1],parts[2]
        elif parts[2] in MONTHS:
            timepart,day,mon=parts[0],parts[1],parts[2]
        else: return None
        tm=hm(timepart)
        try:
            day=int(day); month=MONTHS[mon]
            if tm: return datetime(now.year,month,day,tm[0],tm[1],tzinfo=TZ)
        except Exception: pass
    return None


# =========================================================
# PROCESS TIME
# =========================================================

async def process_time(message: types.Message, state: FSMContext):
    target = parse_time(message.text)
    if not target:
        await message.answer("❌ Vaqt noto'g'ri. Misollar: <code>18:30</code>, <code>18.30</code>, <code>ertaga 18:30</code>, <code>18:30 ertaga</code>, <code>20-09 15:00</code>")
        return
    if target <= datetime.now(TZ):
        await message.answer("❌ Bu vaqt o'tib ketgan. Kelajakdagi vaqtni kiriting.")
        return
    data = await state.get_data(); channel = data.get("selected_channel")
    if not channel:
        channels = get_user_channels(message.from_user.id)
        channel = channels[0][1] if len(channels)==1 else None
    if not channel:
        await message.answer("❌ Kanal tanlanmadi."); await state.clear(); return
    await state.update_data(preview_target=target.isoformat(), selected_channel=channel)
    await state.set_state(PreviewState.waiting_confirmation)
    await message.answer(
        "👀 <b>POST PREVIEW</b>\n\n"
        f"📢 Kanal: <code>{html.escape(channel)}</code>\n"
        f"⏰ Vaqt: <code>{target.strftime('%d.%m.%Y %H:%M')}</code>\n"
        f"🎨 Sticker: <code>{html.escape(data.get('sticker_category','default'))}</code>\n\n"
        "Hammasi to'g'rimi?", reply_markup=preview_keyboard()
    )


# =========================================================
# SEND SCHEDULED POST
# =========================================================

async def send_scheduled_post(post_id):

    cursor.execute("""
        SELECT
            user_id,
            from_chat_id,
            message_id,
            channel,
            sticker_category
        FROM scheduled_posts
        WHERE id = ?
    """, (post_id,))


    result = cursor.fetchone()


    if not result:
        return


    (
        user_id,
        from_chat_id,
        message_id,
        channel,
        sticker_category
    ) = result


    try:

        # Postni kanalga copy qilamiz
        await bot.copy_message(
            chat_id=channel,
            from_chat_id=from_chat_id,
            message_id=message_id
        )


        # Sticker
        sticker = get_matching_sticker(
            sticker_category
        )


        if sticker:

            try:

                await bot.send_sticker(
                    chat_id=channel,
                    sticker=sticker
                )

            except Exception as sticker_error:

                print(
                    "Sticker yuborishda xato:",
                    sticker_error
                )


        cursor.execute("""
            UPDATE scheduled_posts
            SET status = ?
            WHERE id = ?
        """, (
            "sent",
            post_id
        ))

        db.commit()


        print(
            f"POST YUBORILDI -> {channel}"
        )


    except Exception as e:

        print(
            f"POST YUBORISHDA XATO: {e}"
        )


        cursor.execute("""
            UPDATE scheduled_posts
            SET status = ?
            WHERE id = ?
        """, (
            "error",
            post_id
        ))

        db.commit()

        try:
            await bot.send_message(
                user_id,
                "⚠️ <b>Post yuborilmadi</b>\n\n"
                f"📢 Kanal: <code>{html.escape(channel)}</code>\n"
                "Botning kanal admin huquqini va kanal mavjudligini tekshiring."
            )
        except Exception:
            pass


# =========================================================
# ADD STICKER
# =========================================================

STICKER_CATEGORIES = ["salom", "sport", "kulgi", "sevgi", "bayram", "muhim", "oqish", "it", "muvaffaqiyat", "xafa", "default"]


def sticker_category_keyboard():
    rows=[]
    for i in range(0, len(STICKER_CATEGORIES), 2):
        row=[]
        for category in STICKER_CATEGORIES[i:i+2]:
            row.append(InlineKeyboardButton(text=f"🎨 {category}", callback_data=f"sticker_cat:{category}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="❌ Bekor", callback_data="sticker_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(Command("addsticker"))
async def add_sticker(message: types.Message, state: FSMContext):
    register_user(message.from_user)
    await state.clear()
    await state.set_state(StickerState.waiting_category)
    await message.answer("🎨 <b>Sticker qo'shish</b>\n\nKategoriya tanlang:", reply_markup=sticker_category_keyboard())


@dp.callback_query(F.data.startswith("sticker_cat:"))
async def sticker_category_callback(callback: types.CallbackQuery, state: FSMContext):
    category = callback.data.split(":",1)[1]
    if category not in STICKER_CATEGORIES:
        await callback.answer("❌ Noto'g'ri kategoriya", show_alert=True); return
    await state.update_data(sticker_category=category)
    await state.set_state(StickerState.waiting_sticker)
    await callback.message.answer(f"✅ Kategoriya: <code>{category}</code>\n\nEndi <b>stickerning o'zini</b> yuboring.")
    await callback.answer()


@dp.callback_query(F.data == "sticker_cancel")
async def sticker_cancel_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Sticker qo'shish bekor qilindi.")
    await callback.answer()


async def receive_sticker_category(
    message: types.Message,
    state: FSMContext
):

    category = message.text.strip().lower()


    allowed = [
        "salom",
        "sport",
        "kulgi",
        "sevgi",
        "bayram",
        "muhim",
        "oqish",
        "it",
        "muvaffaqiyat",
        "xafa",
        "default"
    ]


    if category not in allowed:

        await message.answer(
            "❌ Bunday kategoriya yo'q.\n\n"
            "Masalan: <code>sport</code>"
        )

        return


    await state.update_data(
        sticker_category=category
    )


    await message.answer(
        f"✅ Kategoriya: <code>{category}</code>\n\n"
        "Endi sticker yuboring."
    )


    await state.set_state(
        StickerState.waiting_sticker
    )


async def receive_sticker(
    message: types.Message,
    state: FSMContext
):

    if not message.sticker:

        await message.answer(
            "❌ Sticker yuboring."
        )

        return


    data = await state.get_data()

    category = data.get(
        "sticker_category",
        "default"
    )


    save_sticker(
        category,
        message.sticker.file_id
    )


    await state.clear()


    await message.answer(
        "✅ <b>Sticker saqlandi!</b>\n\n"
        f"🎨 Kategoriya: <code>{category}</code>"
    )


# =========================================================
# RESTORE SCHEDULED POSTS
# =========================================================

async def restore_scheduled_posts():

    now = datetime.now(TZ)


    cursor.execute("""
        SELECT
            id,
            send_time
        FROM scheduled_posts
        WHERE status = 'pending'
    """)


    rows = cursor.fetchall()


    for post_id, send_time in rows:

        try:

            target = datetime.fromisoformat(
                send_time
            )


            if target <= now:

                cursor.execute("""
                    UPDATE scheduled_posts
                    SET status = ?
                    WHERE id = ?
                """, (
                    "expired",
                    post_id
                ))

                db.commit()

                continue


            scheduler.add_job(
                send_scheduled_post,
                trigger=DateTrigger(
                    run_date=target
                ),
                args=[post_id],
                id=f"post_{post_id}",
                replace_existing=True
            )


        except Exception as e:

            print(
                f"Scheduler restore xatosi: {e}"
            )


# =========================================================
# RENDER WEB SERVER
# =========================================================

async def health(request):

    return web.Response(
        text="Manager BOT ishlayapti! ✅"
    )


async def start_web_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health
    )

    port = int(
        os.getenv("PORT", "10000")
    )


    runner = web.AppRunner(app)

    await runner.setup()


    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )


    await site.start()


    print(
        f"Web server {port} portda ishlayapti."
    )


# =========================================================
# MAIN
# =========================================================

async def main():

    print("🤖 Bot ishga tushmoqda...")


    # Render port
    await start_web_server()


    # Scheduler
    await restore_scheduled_posts()
    await restore_repeating_posts()

    scheduler.start()

    print(
        "⏰ Scheduler ishga tushdi."
    )

    await bot.set_my_commands([
        BotCommand(command="start", description="Botni ishga tushirish"),
        BotCommand(command="channels", description="Kanallarni boshqarish"),
        BotCommand(command="ai", description="AI yordamchi"),
        BotCommand(command="aipost", description="AI orqali post yaratish"),
        BotCommand(command="improve", description="Postni AI bilan yaxshilash"),
        BotCommand(command="caption", description="AI caption yaratish"),
        BotCommand(command="posts", description="Rejalashtirilgan postlar"),
        BotCommand(command="history", description="Postlar tarixi"),
        BotCommand(command="templates", description="Post shablonlari"),
        BotCommand(command="template", description="Shablon olish"),
        BotCommand(command="channelstats", description="Kanal statistikasi"),
        BotCommand(command="addsticker", description="Sticker qo'shish"),
        BotCommand(command="cancel", description="Joriy amalni bekor qilish"),
        BotCommand(command="adminstats", description="Bot statistikasi"),
        BotCommand(command="users", description="Bot foydalanuvchilari"),
        BotCommand(command="admins", description="Adminlarni boshqarish")
    ])

    # Telegram polling
    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "Bot to'xtatildi."
        )
