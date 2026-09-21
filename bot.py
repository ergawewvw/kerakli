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
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger


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


# =========================================================
# STATES
# =========================================================

class SetupState(StatesGroup):
    waiting_channel = State()
    waiting_confirmation = State()
    waiting_time = State()


class StickerState(StatesGroup):
    waiting_category = State()
    waiting_sticker = State()


class EditPostState(StatesGroup):
    waiting_replacement = State()


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


def get_user_channel(user_id):
    cursor.execute(
        "SELECT channel FROM users WHERE user_id = ?",
        (user_id,)
    )

    result = cursor.fetchone()

    if result:
        return result[0]

    return None


def save_user_channel(user_id, channel):
    cursor.execute("""
        UPDATE users
        SET channel = ?
        WHERE user_id = ?
    """, (channel, user_id))

    if cursor.rowcount == 0:
        cursor.execute("""
            INSERT INTO users (user_id, channel)
            VALUES (?, ?)
        """, (user_id, channel))

    db.commit()


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

    channel = get_user_channel(message.from_user.id)

    if channel:

        await message.answer(
            "👋 <b>Manager BOT</b>\n\n"
            f"📢 Kanalingiz: <code>{channel}</code>\n\n"
            "✅ Kanal ulangan.\n\n"
            "Endi post yuboring.\n\n"
            "📅 Rejalashtirilgan postlar: <code>/posts</code>\n"
            "✏️ Tahrirlash / 🗑 O'chirish: /posts"
        )

        return


    await message.answer(
        "👋 <b>Manager BOT</b>\n\n"
        "Avval postingiz chiqadigan kanalni ulang.\n\n"
        "📢 Kanal username'sini yuboring:\n"
        "<code>@kanal_username</code>"
    )

    await state.set_state(
        SetupState.waiting_channel
    )


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
# ADMIN STATISTICS
# =========================================================

def is_admin(user_id):
    return ADMIN_USER_ID != 0 and user_id == ADMIN_USER_ID


@dp.message(Command("adminstats"))
async def admin_stats_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Bu komanda faqat bot egasi uchun.")
        return

    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(DISTINCT channel)
        FROM users
        WHERE channel IS NOT NULL AND channel != ''
    """)
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
            reply_markup=scheduled_posts_keyboard(row[0])
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

    channel = get_user_channel(
        message.from_user.id
    )


    if not channel:

        await message.answer(
            "❌ Avval kanalni ulang.\n\n"
            "/start ni bosing."
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


    await message.answer(
        "📥 <b>POST QABUL QILINDI</b>\n\n"
        f"📢 Kanal: <code>{channel}</code>\n"
        f"🎨 Sticker kategoriyasi: <code>{category}</code>\n\n"
        "⏰ Qachon yuborilsin?\n\n"
        "Masalan:\n"
        "<code>ertaga 18:30</code>\n"
        "<code>20-09 15:00</code>"
    )


    await state.set_state(
        SetupState.waiting_time
    )


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

    text = text.strip().lower()

    now = datetime.now(TZ)


    # -----------------------------------------
    # ertaga 18:30
    # -----------------------------------------

    parts = text.split()

    if len(parts) == 2:

        first = parts[0]
        second = parts[1]


        if first in ["bugun", "today"]:

            target_date = now.date()


        elif first in ["ertaga", "tomorrow"]:

            target_date = (
                now + timedelta(days=1)
            ).date()


        else:

            # 20-09
            try:

                day, month = map(
                    int,
                    first.replace(".", "-").split("-")
                )

                year = now.year

                target_date = datetime(
                    year,
                    month,
                    day,
                    tzinfo=TZ
                ).date()


            except Exception:

                target_date = None


        if target_date:

            try:

                hour, minute = map(
                    int,
                    second.split(":")
                )

                return datetime(
                    target_date.year,
                    target_date.month,
                    target_date.day,
                    hour,
                    minute,
                    tzinfo=TZ
                )

            except Exception:

                return None


    # -----------------------------------------
    # 20 sentabr 18:30
    # -----------------------------------------

    if len(parts) == 3:

        day = parts[0]
        month_name = parts[1]
        time = parts[2]


        if month_name in MONTHS:

            try:

                day = int(day)
                month = MONTHS[month_name]

                hour, minute = map(
                    int,
                    time.split(":")
                )

                year = now.year

                return datetime(
                    year,
                    month,
                    day,
                    hour,
                    minute,
                    tzinfo=TZ
                )

            except Exception:

                return None


    return None


# =========================================================
# PROCESS TIME
# =========================================================

async def process_time(
    message: types.Message,
    state: FSMContext
):

    target = parse_time(
        message.text
    )


    if not target:

        await message.answer(
            "❌ Vaqt formati noto'g'ri.\n\n"
            "To'g'ri misollar:\n"
            "• <code>ertaga 18:30</code>\n"
            "• <code>bugun 21:00</code>\n"
            "• <code>20-09 15:00</code>\n"
            "• <code>20 sentabr 15:00</code>"
        )

        return


    now = datetime.now(TZ)


    if target <= now:

        await message.answer(
            "❌ Bu vaqt allaqachon o'tib ketgan.\n"
            "Kelajakdagi vaqtni kiriting."
        )

        return


    data = await state.get_data()


    channel = get_user_channel(
        message.from_user.id
    )


    if not channel:

        await message.answer(
            "❌ Kanal topilmadi.\n"
            "/start orqali qayta ulang."
        )

        await state.clear()

        return


    post_chat_id = data.get(
        "post_chat_id"
    )

    post_message_id = data.get(
        "post_message_id"
    )

    sticker_category = data.get(
        "sticker_category",
        "default"
    )


    cursor.execute("""
        INSERT INTO scheduled_posts
        (
            user_id,
            from_chat_id,
            message_id,
            channel,
            send_time,
            sticker_category,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        message.from_user.id,
        post_chat_id,
        post_message_id,
        channel,
        target.isoformat(),
        sticker_category,
        "pending"
    ))

    db.commit()


    post_id = cursor.lastrowid


    scheduler.add_job(
        send_scheduled_post,
        trigger=DateTrigger(
            run_date=target
        ),
        args=[post_id],
        id=f"post_{post_id}",
        replace_existing=True
    )


    await state.clear()


    await message.answer(
        "✅ <b>POST REJAGA QO'YILDI!</b>\n\n"
        f"📢 Kanal: <code>{channel}</code>\n"
        f"⏰ Vaqt: <code>{target.strftime('%d.%m.%Y %H:%M')}</code>\n"
        f"🎨 Sticker: <code>{sticker_category}</code>\n\n"
        "Post belgilangan vaqtda avtomatik yuboriladi.\n\n"
        "📅 Rejalashtirilgan postlarni ko'rish: <code>/posts</code>"
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


# =========================================================
# ADD STICKER
# =========================================================

@dp.message(Command("addsticker"))
async def add_sticker(
    message: types.Message,
    state: FSMContext
):

    register_user(message.from_user)
    await message.answer(
        "🎨 <b>Sticker qo'shish</b>\n\n"
        "Kategoriya nomini yuboring:\n\n"
        "salom\n"
        "sport\n"
        "kulgi\n"
        "sevgi\n"
        "bayram\n"
        "muhim\n"
        "oqish\n"
        "it\n"
        "muvaffaqiyat\n"
        "xafa\n"
        "default"
    )


    await state.set_state(
        StickerState.waiting_category
    )


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

    scheduler.start()

    print(
        "⏰ Scheduler ishga tushdi."
    )


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
