import os
import asyncio
import random
import sqlite3
import html
import logging
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import web
from google import genai
from google.genai import types

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


# Render stdout/stderr logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger("manager_bot")

# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi!")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY topilmadi!")

ai_client = genai.Client(api_key=GEMINI_API_KEY)
AI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

TZ = ZoneInfo("Asia/Tashkent")
DB_FILE = "manager.db"

ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=TZ)


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    channel TEXT
)
""")

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS ai_daily_usage (
    user_id INTEGER NOT NULL,
    usage_date TEXT NOT NULL,
    request_count INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, usage_date)
)
""")

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

cursor.execute("""
CREATE TABLE IF NOT EXISTS bot_admins (
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    UNIQUE(user_id, channel)
)
""")

cursor.execute("""
INSERT OR IGNORE INTO user_channels (user_id, channel)
SELECT user_id, channel FROM users
WHERE channel IS NOT NULL AND channel != ''
""")
db.commit()


# =========================================================
# STATES & HELPER FUNCTIONS
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


def register_user(user):
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
    cursor.execute("SELECT id, channel FROM user_channels WHERE user_id = ? ORDER BY id ASC", (user_id,))
    return cursor.fetchall()

def save_user_channel(user_id, channel):
    cursor.execute("INSERT OR IGNORE INTO user_channels (user_id, channel) VALUES (?, ?)", (user_id, channel))
    cursor.execute("UPDATE users SET channel = ? WHERE user_id = ?", (channel, user_id))
    if cursor.rowcount == 0:
        cursor.execute("INSERT OR IGNORE INTO users (user_id, channel) VALUES (?, ?)", (user_id, channel))
    db.commit()

def delete_user_channel(user_id, channel_id):
    cursor.execute("DELETE FROM user_channels WHERE id = ? AND user_id = ?", (channel_id, user_id))
    db.commit()
    return cursor.rowcount > 0

def save_sticker(category, file_id):
    cursor.execute("INSERT INTO stickers (category, file_id) VALUES (?, ?)", (category, file_id))
    db.commit()

def get_stickers(category):
    cursor.execute("SELECT file_id FROM stickers WHERE category = ?", (category,))
    return [row[0] for row in cursor.fetchall()]

def get_all_stickers():
    cursor.execute("SELECT file_id FROM stickers")
    return [row[0] for row in cursor.fetchall()]

def record_ai_usage(user_id):
    today = datetime.now(TZ).date().isoformat()
    daily_limit = int(os.getenv("AI_DAILY_LIMIT", "50"))

    row = cursor.execute("SELECT request_count FROM ai_daily_usage WHERE user_id=? AND usage_date=?", (user_id, today)).fetchone()
    current = row[0] if row else 0
    if current >= daily_limit:
        return False

    cursor.execute("""
        INSERT INTO ai_daily_usage (user_id, usage_date, request_count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, usage_date)
        DO UPDATE SET request_count = request_count + 1
    """, (user_id, today))

    cursor.execute("""
        INSERT INTO ai_usage (user_id, request_count)
        VALUES (?, 1)
        ON CONFLICT(user_id)
        DO UPDATE SET request_count = request_count + 1
    """, (user_id,))

    db.commit()
    return True

def ai_limit_message():
    limit = int(os.getenv("AI_DAILY_LIMIT", "50"))
    return f"⚠️ <b>Kunlik AI limiti tugadi.</b>\n\nBugungi limit: <b>{limit}</b> ta AI so'rovi.\nErtaga yana foydalanishingiz mumkin."

def is_admin(user_id):
    if user_id == ADMIN_USER_ID:
        return True
    row = cursor.execute("SELECT user_id FROM bot_admins WHERE user_id = ?", (user_id,)).fetchone()
    return bool(row)


# =========================================================
# GEMINI AI INTEGRATION
# =========================================================

async def ask_ai(prompt: str) -> str:
    now = datetime.now(TZ)
    current_datetime = now.strftime("%Y-%m-%d %H:%M:%S")
    current_date = now.strftime("%Y-%m-%d")

    system_instruction = (
        "You are the AI assistant inside Manager BOT. "
        "Answer clearly and briefly in Uzbek unless the user asks for another language. "
        "Help with Telegram channel posts, writing, ideas, translation, programming, "
        "and general safe questions. "
        f"IMPORTANT: The current date and time in Tashkent, Uzbekistan is "
        f"{current_datetime} (UTC+05:00), and today's date is {current_date}. "
        "Do not guess or use an older date."
    )

    try:
        response = await asyncio.to_thread(
            ai_client.models.generate_content,
            model=AI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7
            )
        )
        text = (response.text or "").strip()
        return text if text else "❌ AI javob qaytarmadi."
    except Exception as e:
        logger.error(f"Gemini API xatosi: {e}")
        raise e


# =========================================================
# BOT COMMAND HANDLERS
# =========================================================

@dp.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    register_user(message.from_user)
    await state.clear()
    channels = get_user_channels(message.from_user.id)

    if channels:
        lines = ["👋 <b>Manager BOT</b>", "", "📢 <b>Ulangan kanallar:</b>"]
        for i, (_, ch) in enumerate(channels, 1):
            lines.append(f"{i}. <code>{html.escape(ch)}</code>")
        lines += [
            "",
            "➕ Yangi kanal qo'shish: /channels",
            "📅 Rejalashtirilgan postlar: /posts",
            "🤖 AI: /ai",
            "📊 Kanal statistikasi: /stats"
        ]
        await message.answer("\n".join(lines))
        return

    await message.answer(
        "👋 <b>Manager BOT</b>\n\n"
        "Avval kanal ulang. Bir nechta kanalni ham ulashingiz mumkin.\n\n"
        "📢 Kanal username'sini yuboring:\n<code>@kanal_username</code>"
    )
    await state.set_state(SetupState.waiting_channel)

async def check_channel_admin(user_id, channel):
    try:
        user_member = await bot.get_chat_member(channel, user_id)
        if user_member.status not in ["administrator", "creator"]:
            return False, "Siz bu kanalda admin emassiz."

        bot_member = await bot.get_chat_member(channel, (await bot.me()).id)
        if bot_member.status not in ["administrator", "creator"]:
            return False, "Bot kanalga admin qilinmagan.\n\nAvval botni kanalga administrator qilib qo'shing."

        return True, "OK"
    except Exception:
        return False, "Kanalni tekshirib bo'lmadi.\n\nKanal username'si to'g'ri ekanini va bot kanalga admin qilinganini tekshiring."

@dp.message(SetupState.waiting_channel)
async def receive_channel(message: types.Message, state: FSMContext):
    channel = message.text.strip()
    if not channel.startswith("@"):
        await message.answer("❌ Kanal username <code>@</code> bilan boshlanishi kerak.\n\nMasalan:\n<code>@mychannel</code>")
        return

    ok, result = await check_channel_admin(message.from_user.id, channel)
    if not ok:
        await message.answer(f"❌ <b>{result}</b>")
        return

    await state.update_data(channel=channel)
    await message.answer(f"📢 Kanal: <code>{channel}</code>\n\nKanalni ulashni tasdiqlaysizmi?\n\nTasdiqlash uchun:\n<code>TASDIQLASH</code>")
    await state.set_state(SetupState.waiting_confirmation)

@dp.message(SetupState.waiting_confirmation)
async def confirm_channel(message: types.Message, state: FSMContext):
    if message.text.strip().upper() != "TASDIQLASH":
        await message.answer("❌ Tasdiqlash uchun aynan:\n<code>TASDIQLASH</code>\ndeb yozing.")
        return

    data = await state.get_data()
    channel = data.get("channel")
    save_user_channel(message.from_user.id, channel)
    await state.clear()
    await message.answer(f"✅ <b>Kanal muvaffaqiyatli ulandi!</b>\n\n📢 <code>{channel}</code>\n\nEndi post yuboring.\nMasalan, matn yoki rasm + caption.")


# =========================================================
# MULTI-CHANNEL & COMMANDS
# =========================================================

def channel_manage_keyboard(user_id):
    rows = []
    for channel_id, channel in get_user_channels(user_id):
        rows.append([InlineKeyboardButton(text=f"📢 {channel}", callback_data=f"select_channel:{channel_id}")])
    rows.append([InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="add_channel")])
    if get_user_channels(user_id):
        rows.append([InlineKeyboardButton(text="🗑 Kanal o'chirish", callback_data="delete_channel_menu")])
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
    text = "📢 <b>Mening kanallarim</b>\n\n" + "\n".join(f"{i}. <code>{html.escape(ch)}</code>" for i, (_, ch) in enumerate(channels, 1))
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
    await callback.message.answer(f"✅ Kanal tanlandi: <code>{html.escape(channel)}</code>\n\n⏰ Qachon yuborilsin?\nMasalan: <code>ertaga 18:30</code> yoki <code>10 daqiqadan keyin</code>")
    await callback.answer()


# =========================================================
# AI COMMAND HANDLERS
# =========================================================

@dp.message(Command("ai"))
async def ai_handler(message: types.Message):
    register_user(message.from_user)
    prompt = (message.text or "").partition(" ")[2].strip()

    if not prompt:
        await message.answer("🤖 <b>AI yordamchi</b>\n\nSavolingizni /ai dan keyin yozing.\n\nMasalan:\n<code>/ai Telegram kanal uchun motivatsion post yoz</code>")
        return

    await message.answer("🤖 AI o'ylayapti...")
    try:
        if not record_ai_usage(message.from_user.id):
            await message.answer(ai_limit_message())
            return
        answer = await ask_ai(prompt)
        await message.answer(html.escape(answer))
    except Exception:
        logger.exception("Gemini AI xatosi")
        await message.answer("❌ AI bilan bog'lanishda xatolik yuz berdi.")

@dp.message(Command("aipost"))
async def ai_post_handler(message: types.Message):
    register_user(message.from_user)
    prompt = (message.text or "").partition(" ")[2].strip()

    if not prompt:
        await message.answer("📝 <b>AI Post</b>\n\nMasalan:\n<code>/aipost Bugun dasturlash haqida motivatsion post</code>")
        return

    await message.answer("📝 AI post tayyorlayapti...")
    try:
        if not record_ai_usage(message.from_user.id):
            await message.answer(ai_limit_message())
            return
        answer = await ask_ai(f"Telegram kanal uchun tayyor post yoz. Ortiqcha izohsiz, faqat post matnini ber. Mavzu: {prompt}")
        await message.answer("✅ <b>AI tayyorlagan post:</b>\n\n" + html.escape(answer))
    except Exception:
        logger.exception("Gemini post xatosi")
        await message.answer("❌ AI post yaratishda xatolik yuz berdi.")

@dp.message(Command("improve"))
async def improve_handler(message: types.Message):
    prompt = (message.text or "").partition(" ")[2].strip()
    if not prompt:
        await message.answer("✨ <b>AI postni yaxshilash</b>\n\nMasalan: <code>/improve Bugun yangi kursimiz boshlandi...</code>")
        return
    try:
        if not record_ai_usage(message.from_user.id):
            await message.answer(ai_limit_message())
            return
        answer = await ask_ai("Quyidagi Telegram postini mazmunini saqlagan holda chiroyli, xatosiz, o'qilishi oson qilib formatla. Sarlavha, mos emoji va kerak bo'lsa 2-4 hashtag qo'sh. Faqat tayyor postni qaytar.\n\n" + prompt)
        await message.answer("✨ <b>Yaxshilangan post:</b>\n\n" + html.escape(answer))
    except Exception:
        await message.answer("❌ AI postni yaxshilay olmadi.")

@dp.message(Command("caption"))
async def caption_handler(message: types.Message):
    prompt = (message.text or "").partition(" ")[2].strip()
    if not prompt:
        await message.answer("🖼️ <b>AI caption</b>\n\nMasalan: <code>/caption Yangi futbol formasi reklamasi</code>")
        return
    try:
        if not record_ai_usage(message.from_user.id):
            await message.answer(ai_limit_message())
            return
        answer = await ask_ai("Telegram uchun qisqa va qiziqarli caption yoz. 1-3 emoji va 2-4 hashtag qo'sh. Faqat captionni qaytar. Mavzu: " + prompt)
        await message.answer("🖼️ <b>Caption:</b>\n\n" + html.escape(answer))
    except Exception:
        await message.answer("❌ Caption yaratishda xatolik.")


# =========================================================
# TEMPLATES & STATS & ADMIN
# =========================================================

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
    await message.answer("📝 <b>Post shablonlari</b>\n\n<code>/template reklama</code>\n<code>/template yangilik</code>\n<code>/template elon</code>\n<code>/template motivatsiya</code>")

@dp.message(Command("template"))
async def template_handler(message: types.Message):
    kind = (message.text or "").partition(" ")[2].strip().lower()
    text = template_text(kind)
    if not text:
        await message.answer("❌ Shablon topilmadi. /templates ni bosing.")
        return
    await message.answer(text)

@dp.message(Command("history"))
async def history_handler(message: types.Message):
    rows = cursor.execute("SELECT id, channel, send_time, status FROM scheduled_posts WHERE user_id = ? AND status != 'pending' ORDER BY id DESC LIMIT 20", (message.from_user.id,)).fetchall()
    if not rows:
        await message.answer("📭 Hali postlar tarixi yo'q.")
        return
    lines = ["📜 <b>Postlar tarixi</b>", ""]
    for pid, channel, send_time, status in rows:
        try:
            t = datetime.fromisoformat(send_time).astimezone(TZ).strftime("%d.%m %H:%M")
        except Exception:
            t = send_time
        icon = {"sent":"✅", "error":"❌", "cancelled":"🗑", "expired":"⌛"}.get(status, "•")
        lines.append(f"{icon} #{pid} — <code>{html.escape(channel)}</code> — {t} — {status}")
    await message.answer("\n".join(lines))

@dp.message(Command("stats"))
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

@dp.message(Command("admins"))
async def admins_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ Faqat admin uchun.")
        return
    rows = cursor.execute("SELECT user_id FROM bot_admins ORDER BY user_id").fetchall()
    text = f"👑 <b>Bot adminlari</b>\n\n👑 Owner: <code>{ADMIN_USER_ID}</code>\n"
    if rows:
        text += "\n".join(f"• Admin: <code>{r[0]}</code>" for r in rows)
    else:
        text += "Qo'shimcha adminlar: yo'q"
    text += "\n\n➕ Qo'shish: <code>/adminadd USER_ID</code>\n🗑 O'chirish: <code>/admindel USER_ID</code>"
    await message.answer(text)

@dp.message(Command("adminadd"))
async def adminadd_handler(message: types.Message):
    if ADMIN_USER_ID != message.from_user.id:
        await message.answer("❌ Faqat bot egasi yangi admin qo'sha oladi.")
        return
    arg = (message.text or "").partition(" ")[2].strip()
    try:
        uid = int(arg)
    except ValueError:
        await message.answer("❌ Masalan: <code>/adminadd 123456789</code>")
        return
    cursor.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (uid,))
    db.commit()
    await message.answer(f"✅ <code>{uid}</code> admin qilindi.")

@dp.message(Command("admindel"))
async def admindel_handler(message: types.Message):
    if ADMIN_USER_ID != message.from_user.id:
        await message.answer("❌ Faqat bot egasi adminni o'chira oladi.")
        return
    arg = (message.text or "").partition(" ")[2].strip()
    try:
        uid = int(arg)
    except ValueError:
        await message.answer("❌ Masalan: <code>/admindel 123456789</code>")
        return
    cursor.execute("DELETE FROM bot_admins WHERE user_id = ?", (uid,))
    db.commit()
    await message.answer(f"🗑 <code>{uid}</code> adminlikdan olindi.")


# =========================================================
# WEB SERVER & MAIN LAUNCH
# =========================================================

async def handle_ping(request):
    return web.Response(text="Bot is alive and running!")

async def main():
    scheduler.start()

    # Render uchun HTTP Server
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info(f"Web server {port}-portda ishga tushdi.")

    # Telegram Bot Polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
