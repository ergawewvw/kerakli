import os
import asyncio
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger


BOT_TOKEN = os.getenv("BOT_TOKEN")
TZ = ZoneInfo("Asia/Tashkent")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    )
)

dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=TZ)


# =========================================================
# MA'LUMOTLAR
# =========================================================

user_channels = {}
user_messages = {}

# Stickerlar shu yerda saqlanadi
stickers = {
    "salom": [],
    "sport": [],
    "kulgi": [],
    "sevgi": [],
    "bayram": [],
    "muhim": [],
    "oqish": [],
    "it": [],
    "muvaffaqiyat": [],
    "xafa": [],
    "default": []
}


class SetupState(StatesGroup):
    waiting_channel = State()
    waiting_confirmation = State()
    waiting_time = State()


# Sticker qo'shish uchun vaqtinchalik state
class StickerState(StatesGroup):
    waiting_category = State()
    waiting_sticker = State()


# =========================================================
# START
# =========================================================

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):

    await state.clear()

    user_id = message.from_user.id

    if user_id in user_channels:

        channel = user_channels[user_id]

        await message.answer(
            "🎉 <b>Xush kelibsiz!</b>\n\n"
            f"📢 Ulangan kanal: <b>{channel}</b>\n\n"
            "📨 Menga post yuboring.\n"
            "⏰ Keyin vaqtini so'rayman.\n\n"
            "🤖 Postga mos sticker ham avtomatik tanlanadi!"
        )

    else:

        await message.answer(
            "👋 <b>Salom!</b> 🤖\n\n"
            "📢 Avval kanalingizni ulang.\n\n"
            "1️⃣ Botni kanalingizga administrator qiling.\n"
            "2️⃣ Kanal username'ini yuboring.\n\n"
            "💡 Masalan:\n"
            "<code>@meningkanalim</code>"
        )

        await state.set_state(SetupState.waiting_channel)


# =========================================================
# KANAL ULASH
# =========================================================

async def connect_channel(message: types.Message, state: FSMContext):

    channel = (message.text or "").strip()

    if not channel.startswith("@"):

        await message.answer(
            "❌ <b>Kanal username noto'g'ri!</b>\n\n"
            "Masalan:\n"
            "<code>@meningkanalim</code>"
        )

        return

    try:

        chat = await bot.get_chat(channel)

        user_member = await bot.get_chat_member(
            chat.id,
            message.from_user.id
        )

        if user_member.status not in ["administrator", "creator"]:

            await message.answer(
                "🚫 <b>Kanal tasdiqlanmadi!</b>\n\n"
                "👤 Siz bu kanal administratori emassiz."
            )

            return

        bot_member = await bot.get_chat_member(
            chat.id,
            bot.id
        )

        if bot_member.status not in ["administrator", "creator"]:

            await message.answer(
                "⚠️ <b>Bot kanal administratori emas!</b>\n\n"
                "📢 Avval botni administrator qiling."
            )

            return

        await state.update_data(
            pending_channel=channel
        )

        await message.answer(
            "🔍 <b>1-BOSQICH MUVAFFAQIYATLI!</b> ✅\n\n"
            f"📢 Kanal: <code>{channel}</code>\n"
            "👤 Siz: Administrator ✅\n"
            "🤖 Bot: Administrator ✅\n\n"
            "🔐 Kanalni ulash uchun:\n\n"
            "👉 <b>TASDIQLASH</b>\n\n"
            "deb yozing."
        )

        await state.set_state(
            SetupState.waiting_confirmation
        )

    except Exception as e:

        print("CHANNEL ERROR:", e)

        await message.answer(
            "❌ <b>Kanalni tekshirib bo'lmadi!</b>\n\n"
            "Kanal username'ini tekshiring."
        )


# =========================================================
# TASDIQLASH
# =========================================================

async def confirm_channel(
    message: types.Message,
    state: FSMContext
):

    text = (message.text or "").strip().lower()

    if text not in [
        "tasdiqlash",
        "tasdiqlayman",
        "ha"
    ]:

        await message.answer(
            "🔐 <b>Tasdiqlash kerak!</b>\n\n"
            "👉 <b>TASDIQLASH</b> deb yozing."
        )

        return

    data = await state.get_data()

    channel = data.get("pending_channel")

    if not channel:

        await message.answer(
            "❌ Kanal ma'lumoti topilmadi.\n\n"
            "🔄 /start ni bosing."
        )

        await state.clear()

        return

    try:

        chat = await bot.get_chat(channel)

        user_member = await bot.get_chat_member(
            chat.id,
            message.from_user.id
        )

        bot_member = await bot.get_chat_member(
            chat.id,
            bot.id
        )

        if user_member.status not in [
            "administrator",
            "creator"
        ]:

            await message.answer(
                "🚫 <b>Siz kanal administratori emassiz!</b>"
            )

            return

        if bot_member.status not in [
            "administrator",
            "creator"
        ]:

            await message.answer(
                "🤖 <b>Bot kanal administratori emas!</b>"
            )

            return

        user_channels[
            message.from_user.id
        ] = channel

        await state.clear()

        await message.answer(
            "🎉 <b>KANAL MUVAFFAQIYATLI ULANDI!</b> 🎉\n\n"
            f"📢 Kanal: <b>{channel}</b>\n\n"
            "📨 Endi post yuboring!\n\n"
            "🤖 Bot postni tahlil qiladi\n"
            "🎯 Mos kategoriyani topadi\n"
            "✨ Mos sticker tanlaydi\n"
            "⏰ Belgilangan vaqtda yuboradi."
        )

    except Exception as e:

        print("CONFIRM ERROR:", e)

        await message.answer(
            "❌ <b>Tasdiqlashda xatolik!</b>"
        )


# =========================================================
# POST QABUL QILISH
# =========================================================

async def save_post(
    message: types.Message,
    state: FSMContext
):

    user_id = message.from_user.id

    user_messages[user_id] = message

    await state.set_state(
        SetupState.waiting_time
    )

    await message.answer(
        "📨 <b>POST QABUL QILINDI!</b> ✅\n\n"
        "🤖 Matnni tahlil qildim.\n"
        "✨ Mos sticker avtomatik tanlanadi.\n\n"
        "⏰ Endi qachon kanalga joylay?\n\n"
        "💡 Masalan:\n\n"
        "🌙 <code>ertaga 20:00</code>\n"
        "📅 <code>18-sentabr 10:00</code>"
    )


# =========================================================
# MATNNI TAHLIL QILISH
# =========================================================

def choose_sticker_category(text):

    text = text.lower()

    categories = {

        "salom": [
            "salom",
            "assalom",
            "xayrli tong",
            "xayrli kun",
            "xayrli kech",
            "hello",
            "hi"
        ],

        "sport": [
            "futbol",
            "football",
            "sport",
            "gol",
            "g'alaba",
            "chempionat",
            "match",
            "o'yin",
            "basketbol",
            "tennis"
        ],

        "kulgi": [
            "hazil",
            "kulgili",
            "haha",
            "😂",
            "lol",
            "mem",
            "prikol"
        ],

        "sevgi": [
            "sevgi",
            "sevaman",
            "yurak",
            "❤️",
            "love",
            "muhabbat"
        ],

        "bayram": [
            "bayram",
            "tug'ilgan kun",
            "tabrik",
            "yangi yil",
            "navro'z",
            "ramazon",
            "hayit",
            "🎉"
        ],

        "muhim": [
            "muhim",
            "diqqat",
            "e'lon",
            "tezkor",
            "yangilik",
            "xabar",
            "rasmiy"
        ],

        "oqish": [
            "maktab",
            "dars",
            "imtihon",
            "o'qish",
            "kitob",
            "ustoz",
            "talaba",
            "o'quvchi",
            "matematika",
            "fizika",
            "kimyo"
        ],

        "it": [
            "python",
            "kod",
            "dasturlash",
            "programming",
            "developer",
            "github",
            "html",
            "css",
            "java",
            "c++",
            "javascript"
        ],

        "muvaffaqiyat": [
            "g'alaba",
            "yutdim",
            "yutdik",
            "muvaffaqiyat",
            "tabriklayman",
            "zo'r",
            "ajoyib",
            "super",
            "top"
        ],

        "xafa": [
            "xafa",
            "afsus",
            "achinarli",
            "yomon",
            "yo'qotdik",
            "😢",
            "😭"
        ]
    }

    # Mos kategoriyalarni hisoblaymiz
    found = []

    for category, words in categories.items():

        for word in words:

            if word in text:
                found.append(category)
                break

    if found:

        # Agar bir nechta kategoriya topilsa,
        # oxirgi emas, tasodifiy mos kategoriyani tanlaymiz
        return random.choice(found)

    return "default"


# =========================================================
# STICKER TANLASH
# =========================================================

def get_matching_sticker(text):

    category = choose_sticker_category(text)

    available = stickers.get(category, [])

    if available:

        return random.choice(available)

    # Agar mos kategoriyada sticker bo'lmasa
    all_stickers = []

    for values in stickers.values():

        all_stickers.extend(values)

    if all_stickers:

        return random.choice(all_stickers)

    return None


# =========================================================
# VAQTNI QABUL QILISH
# =========================================================

async def process_time(
    message: types.Message,
    state: FSMContext
):

    text = (message.text or "").lower().strip()

    now = datetime.now(TZ)

    try:

        if text.startswith("ertaga"):

            time_text = text.replace(
                "ertaga",
                ""
            ).strip()

            hour, minute = map(
                int,
                time_text.split(":")
            )

            send_time = now.replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0
            ) + timedelta(days=1)

        else:

            date_text, time_text = text.split()

            day = int(
                date_text.split("-")[0]
            )

            month_name = date_text.split("-")[1]

            months = {
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

            month = months[month_name]

            hour, minute = map(
                int,
                time_text.split(":")
            )

            send_time = datetime(
                now.year,
                month,
                day,
                hour,
                minute,
                tzinfo=TZ
            )

            if send_time <= now:

                await message.answer(
                    "⚠️ <b>Bu vaqt o'tib ketgan.</b>\n\n"
                    "⏰ Kelajakdagi vaqtni yozing."
                )

                return

        user_id = message.from_user.id

        original_message = user_messages.get(
            user_id
        )

        channel = user_channels.get(
            user_id
        )

        if not original_message:

            await message.answer(
                "❌ Post topilmadi.\n\n"
                "📨 Avval post yuboring."
            )

            await state.clear()

            return

        if not channel:

            await message.answer(
                "❌ Kanal ulanmagan."
            )

            await state.clear()

            return

        scheduler.add_job(
            send_to_channel,
            trigger=DateTrigger(
                run_date=send_time
            ),
            args=[
                original_message,
                channel
            ]
        )

        await message.answer(
            "🎉 <b>POST REJALASHTIRILDI!</b> 🎉\n\n"
            f"📢 Kanal: <b>{channel}</b>\n"
            f"📅 Sana: <b>{send_time.strftime('%d.%m.%Y')}</b>\n"
            f"⏰ Vaqt: <b>{send_time.strftime('%H:%M')}</b>\n\n"
            "🤖 Matn tahlil qilinadi.\n"
            "✨ Mos sticker tanlanadi.\n"
            "🚀 Belgilangan vaqtda yuboraman!"
        )

        await state.clear()

    except Exception as e:

        print("TIME ERROR:", e)

        await message.answer(
            "😅 <b>Vaqtni tushunmadim!</b>\n\n"
            "Masalan:\n"
            "<code>ertaga 20:00</code>\n"
            "<code>18-sentabr 10:00</code>"
        )


# =========================================================
# POSTNI KANALGA YUBORISH
# =========================================================

async def send_to_channel(
    message: types.Message,
    channel: str
):

    try:

        # Avval original post
        await bot.copy_message(
            chat_id=channel,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )

        print(
            f"✅ POST YUBORILDI → {channel}"
        )

        # Post matnini olamiz
        text = message.text or message.caption or ""

        # Mos sticker tanlaymiz
        sticker = get_matching_sticker(text)

        if sticker:

            await bot.send_sticker(
                chat_id=channel,
                sticker=sticker
            )

            print(
                f"✨ STICKER YUBORILDI → {channel}"
            )

        else:

            print(
                "ℹ️ Stickerlar hali qo'shilmagan."
            )

    except Exception as e:

        print(
            f"❌ POST YUBORILMADI → {channel}"
        )

        print(e)


# =========================================================
# STICKER QO'SHISH
# =========================================================

@dp.message(Command("addsticker"))
async def add_sticker_start(
    message: types.Message,
    state: FSMContext
):

    await state.clear()

    await message.answer(
        "✨ <b>STICKER QO'SHISH</b>\n\n"
        "Sticker yubormoqchi bo'lgan kategoriyani yozing:\n\n"
        "👋 <code>salom</code>\n"
        "⚽ <code>sport</code>\n"
        "😂 <code>kulgi</code>\n"
        "❤️ <code>sevgi</code>\n"
        "🎉 <code>bayram</code>\n"
        "📢 <code>muhim</code>\n"
        "📚 <code>oqish</code>\n"
        "💻 <code>it</code>\n"
        "🏆 <code>muvaffaqiyat</code>\n"
        "😢 <code>xafa</code>\n"
        "🎲 <code>default</code>\n\n"
        "Masalan: <code>sport</code>"
    )

    await state.set_state(
        StickerState.waiting_category
    )


@dp.message(StickerState.waiting_category)
async def sticker_category(
    message: types.Message,
    state: FSMContext
):

    category = (
        message.text or ""
    ).lower().strip()

    if category not in stickers:

        await message.answer(
            "❌ Bunday kategoriya yo'q.\n\n"
            "Masalan: <code>sport</code>"
        )

        return

    await state.update_data(
        sticker_category=category
    )

    await message.answer(
        f"📂 Kategoriya: <b>{category}</b>\n\n"
        "✨ Endi stickerning o'zini yuboring."
    )

    await state.set_state(
        StickerState.waiting_sticker
    )


@dp.message(StickerState.waiting_sticker)
async def sticker_received(
    message: types.Message,
    state: FSMContext
):

    if not message.sticker:

        await message.answer(
            "❌ Iltimos, aynan <b>sticker</b> yuboring."
        )

        return

    data = await state.get_data()

    category = data.get(
        "sticker_category"
    )

    sticker_id = message.sticker.file_id

    stickers[category].append(
        sticker_id
    )

    await state.clear()

    await message.answer(
        "✅ <b>STICKER SAQLANDI!</b>\n\n"
        f"📂 Kategoriya: <b>{category}</b>\n"
        f"✨ Shu kategoriyada: <b>{len(stickers[category])}</b> ta sticker\n\n"
        "Yana qo'shish uchun:\n"
        "<code>/addsticker</code>"
    )


# =========================================================
# BARCHA XABARLAR
# =========================================================

@dp.message()
async def all_messages(
    message: types.Message,
    state: FSMContext
):

    current_state = await state.get_state()

    if current_state == SetupState.waiting_channel.state:

        await connect_channel(
            message,
            state
        )

        return

    if current_state == SetupState.waiting_confirmation.state:

        await confirm_channel(
            message,
            state
        )

        return

    if current_state == SetupState.waiting_time.state:

        await process_time(
            message,
            state
        )

        return

    if current_state == StickerState.waiting_category.state:

        await sticker_category(
            message,
            state
        )

        return

    if current_state == StickerState.waiting_sticker.state:

        await sticker_received(
            message,
            state
        )

        return

    user_id = message.from_user.id

    if user_id not in user_channels:

        await message.answer(
            "🔒 <b>Avval kanalni ulang!</b>\n\n"
            "📢 Kanal username'ini yuboring.\n\n"
            "Masalan:\n"
            "<code>@meningkanalim</code>"
        )

        await state.set_state(
            SetupState.waiting_channel
        )

        return

    await save_post(
        message,
        state
    )


# =========================================================
# MAIN
# =========================================================

async def main():

    print("🤖 Bot ishga tushmoqda...")

    scheduler.start()

    print("⏰ Scheduler ishga tushdi.")

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
