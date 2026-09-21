import os
import asyncio
import random
import sqlite3
import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import web
from openai import AsyncOpenAI

from aiogram import Bot, Dispatcher, types
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


# =========================================================
# DATABASE FUNCTIONS
# =========================================================

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
        INSERT OR REPLACE INTO users (user_id, channel)
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


# =========================================================
# START
# =========================================================

@dp.message(Command("start"))
async def start_handler(
    message: types.Message,
    state: FSMContext
):

    await state.clear()

    channel = get_user_channel(message.from_user.id)

    if channel:

        await message.answer(
            "👋 <b>Manager BOT</b>\n\n"
            f"📢 Kanalingiz: <code>{channel}</code>\n\n"
            "✅ Kanal ulangan.\n\n"
            "Endi post yuboring."
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
# SAVE POST
# =========================================================

@dp.message()
async def all_messages(
    message: types.Message,
    state: FSMContext
):

    current_state = await state.get_state()


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
        "<code>18:30</code> — bugun\n"
        "<code>18.30</code> — bugun\n"
        "<code>18 30</code> — bugun\n"
        "<code>18:30 ertaga</code>\n"
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
    """Vaqtni bir nechta qulay formatda qabul qiladi.

    Qabul qilinadigan formatlar:
    18:30              -> bugun 18:30
    18.30              -> bugun 18:30
    18 30              -> bugun 18:30
    ertaga 18:30       -> ertaga 18:30
    18:30 ertaga       -> ertaga 18:30
    bugun 18:30        -> bugun 18:30
    20-09 15:00        -> 20-sentabr 15:00
    15:00 20-09        -> 20-sentabr 15:00
    20 sentabr 15:00   -> 20-sentabr 15:00
    15:00 20 sentabr   -> 20-sentabr 15:00
    """
    text = text.strip().lower()
    text = text.replace(",", " ")
    now = datetime.now(TZ)

    # Nuqta yoki bo'shliq bilan yozilgan soatni standartlashtiramiz.
    # Masalan: 18.30 -> 18:30, 18 30 -> 18:30
    text = text.replace(".", ":")
    raw_parts = text.split()

    if not raw_parts:
        return None

    # "18 30" -> "18:30"
    parts = []
    i = 0
    while i < len(raw_parts):
        if (
            i + 1 < len(raw_parts)
            and raw_parts[i].isdigit()
            and raw_parts[i + 1].isdigit()
            and 0 <= int(raw_parts[i]) <= 23
            and 0 <= int(raw_parts[i + 1]) <= 59
        ):
            parts.append(f"{raw_parts[i]}:{raw_parts[i + 1]}")
            i += 2
        else:
            parts.append(raw_parts[i])
            i += 1

    def parse_clock(value):
        value = value.strip()
        if ":" not in value:
            return None
        try:
            hour, minute = map(int, value.split(":", 1))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            return hour, minute
        except (ValueError, TypeError):
            return None

    def parse_numeric_date(value):
        try:
            day, month = map(int, value.replace("/", "-").split("-"))
            if not (1 <= day <= 31 and 1 <= month <= 12):
                return None
            return day, month
        except (ValueError, TypeError):
            return None

    def make_datetime(day, month, hour, minute):
        try:
            year = now.year
            target = datetime(year, month, day, hour, minute, tzinfo=TZ)
            # Agar sana bu yil o'tib ketgan bo'lsa, keyingi yilga o'tkazamiz.
            if target.date() < now.date() and month < now.month:
                target = target.replace(year=year + 1)
            return target
        except ValueError:
            return None

    # 1) Faqat vaqt: 18:30 / 18.30 / 18 30 -> bugun
    if len(parts) == 1:
        clock = parse_clock(parts[0])
        if clock:
            hour, minute = clock
            return datetime(now.year, now.month, now.day, hour, minute, tzinfo=TZ)
        return None

    # 2) "vaqt + sana/kun" yoki "sana/kun + vaqt"
    # Masalan: 18:30 ertaga, ertaga 18:30, 18:30 20-09, 20-09 18:30
    clock = None
    date_day = None
    date_month = None
    relative = None

    for part in parts:
        c = parse_clock(part)
        if c and clock is None:
            clock = c
            continue

        if part in ("bugun", "today"):
            relative = "today"
            continue
        if part in ("ertaga", "tomorrow"):
            relative = "tomorrow"
            continue

        numeric = parse_numeric_date(part)
        if numeric:
            date_day, date_month = numeric
            continue

    # 3) Oy nomi bilan sana: 20 sentabr 18:30 yoki 18:30 20 sentabr
    if clock is not None and date_day is None:
        for i, part in enumerate(parts):
            if part in MONTHS and i > 0 and parts[i - 1].isdigit():
                date_day = int(parts[i - 1])
                date_month = MONTHS[part]
                break

    if clock is None:
        return None

    hour, minute = clock

    if relative == "tomorrow":
        target_date = (now + timedelta(days=1)).date()
        return datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=TZ)

    if relative == "today":
        return datetime(now.year, now.month, now.day, hour, minute, tzinfo=TZ)

    if date_day is not None and date_month is not None:
        return make_datetime(date_day, date_month, hour, minute)

    # Agar faqat vaqtga qo'shimcha noma'lum so'z berilgan bo'lsa, qabul qilmaymiz.
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
            "• <code>18:30</code> — bugun\n"
            "• <code>18.30</code> — bugun\n"
            "• <code>18 30</code> — bugun\n"
            "• <code>18:30 ertaga</code>\n"
            "• <code>ertaga 18:30</code>\n"
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
        "Post belgilangan vaqtda avtomatik yuboriladi."
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
