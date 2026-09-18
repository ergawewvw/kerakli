import os
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger


# =========================
# SOZLAMALAR
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")

TZ = ZoneInfo("Asia/Tashkent")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

scheduler = AsyncIOScheduler(timezone=TZ)

# Har bir foydalanuvchining kanali
user_channels = {}

# Har bir foydalanuvchining yuborgan xabari
user_messages = {}


# =========================
# HOLATLAR
# =========================

class SetupState(StatesGroup):
    waiting_channel = State()
    waiting_post = State()
    waiting_time = State()


# =========================
# /start
# =========================

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):

    await state.clear()

    user_id = message.from_user.id

    if user_id in user_channels:

        await message.answer(
            "👋 Salom!\n\n"
            f"📢 Ulangan kanal: {user_channels[user_id]}\n\n"
            "Endi menga post yuborishing mumkin."
        )

    else:

        await message.answer(
            "👋 Salom!\n\n"
            "Botdan foydalanish uchun avval kanalingni ulashing.\n\n"
            "1️⃣ Botni kanalingga ADMIN qilib qo‘sh.\n"
            "2️⃣ Kanal username'ini yubor.\n\n"
            "Masalan:\n"
            "@meningkanalim"
        )

        await state.set_state(
            SetupState.waiting_channel
        )


# =========================
# KANALNI ULASH
# =========================

@dp.message(SetupState.waiting_channel)
async def connect_channel(
    message: types.Message,
    state: FSMContext
):

    channel = (message.text or "").strip()

    if not channel.startswith("@"):

        await message.answer(
            "❌ Kanal username'i @ bilan boshlanishi kerak.\n\n"
            "Masalan:\n"
            "@meningkanalim"
        )
        return

    try:

        chat = await bot.get_chat(channel)

        member = await bot.get_chat_member(
            chat.id,
            bot.id
        )

        if member.status not in ["administrator", "creator"]:

            await message.answer(
                "❌ Men bu kanalda admin emasman.\n\n"
                "Avval botni kanalingga administrator qilib qo‘sh."
            )
            return

        user_id = message.from_user.id

        user_channels[user_id] = channel

        await state.clear()

        await message.answer(
            "✅ Kanal muvaffaqiyatli ulandi!\n\n"
            f"📢 Kanal: {channel}\n\n"
            "Endi menga matn, rasm yoki video yubor."
        )

    except Exception as e:

        print(f"Channel error: {e}")

        await message.answer(
            "❌ Kanalni topa olmadim.\n\n"
            "Tekshir:\n"
            "• Kanal username'i to‘g‘ri yozilganmi?\n"
            "• Bot kanalga admin qilib qo‘shilganmi?\n\n"
            "Masalan:\n"
            "@meningkanalim"
        )


# =========================
# POST QABUL QILISH
# =========================

@dp.message(SetupState.waiting_post)
async def receive_post_waiting(
    message: types.Message,
    state: FSMContext
):

    await save_post(message, state)


# =========================
# UMUMIY XABAR
# =========================

@dp.message()
async def receive_message(
    message: types.Message,
    state: FSMContext
):

    if message.text and message.text.startswith("/"):
        return

    user_id = message.from_user.id

    # Kanal ulanmagan
    if user_id not in user_channels:

        await message.answer(
            "❌ Avval kanalingni ulashing.\n\n"
            "Kanal username'ini yubor:\n"
            "@meningkanalim"
        )

        await state.set_state(
            SetupState.waiting_channel
        )
        return

    await save_post(message, state)


# =========================
# POSTNI SAQLASH
# =========================

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
        "📅 Qachon kanalga joylay?\n\n"
        "Masalan:\n"
        "• ertaga 20:00\n"
        "• 25-sentabr 20:00"
    )


# =========================
# VAQTNI QABUL QILISH
# =========================

@dp.message(SetupState.waiting_time)
async def set_time(
    message: types.Message,
    state: FSMContext
):

    text = (message.text or "").lower().strip()

    if not text:

        await message.answer(
            "❌ Vaqtni matn ko‘rinishida yubor.\n\n"
            "Masalan: ertaga 20:00"
        )
        return

    now = datetime.now(TZ)

    try:

        # =========================
        # ERTAGA
        # =========================

        if text.startswith("ertaga"):

            time_text = text.replace(
                "ertaga", ""
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

        # =========================
        # SANA
        # =========================

        else:

            date_text, time_text = text.split()

            day = int(
                date_text.split("-")[0]
            )

            month_name = (
                date_text.split("-")[1]
            )

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
                "dekabr": 12,
            }

            if month_name not in months:
                raise ValueError()

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

                send_time = datetime(
                    now.year + 1,
                    month,
                    day,
                    hour,
                    minute,
                    tzinfo=TZ
                )

        original_message = user_messages.get(
            message.from_user.id
        )

        if not original_message:

            await message.answer(
                "❌ Avval post yubor."
            )
            return

        channel = user_channels.get(
            message.from_user.id
        )

        if not channel:

            await message.answer(
                "❌ Avval kanalni ulang."
            )
            return

        scheduler.add_job(
            send_to_channel,
            trigger=DateTrigger(
                run_date=send_time
            ),
            args=[
                original_message,
                channel
            ],
        )

        await message.answer(
            "✅ Rejalashtirildi!\n\n"
            f"📢 Kanal: {channel}\n"
            f"📅 Sana: {send_time.strftime('%d.%m.%Y')}\n"
            f"⏰ Vaqt: {send_time.strftime('%H:%M')}"
        )

        await state.clear()

    except Exception:

        await message.answer(
            "❌ Vaqt noto‘g‘ri yozildi.\n\n"
            "Masalan:\n"
            "ertaga 20:00\n"
            "25-sentabr 20:00"
        )


# =========================
# KANALGA YUBORISH
# =========================

async def send_to_channel(
    message: types.Message,
    channel: str
):

    try:

        await bot.copy_message(
            chat_id=channel,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )

        print(
            f"✅ Post yuborildi: {channel}"
        )

    except Exception as e:

        print(
            f"❌ Post yuborishda xato: {e}"
        )


# =========================
# BOTNI ISHGA TUSHIRISH
# =========================

async def main():

    print("🤖 Bot ishga tushmoqda...")

    scheduler.start()

    print("⏰ Scheduler ishga tushdi.")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
