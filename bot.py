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
CHANNEL = os.getenv("CHANNEL", "@nothing_ls_forever")

TZ = ZoneInfo("Asia/Tashkent")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

scheduler = AsyncIOScheduler(timezone=TZ)


# =========================
# HOLATLAR
# =========================

class ScheduleState(StatesGroup):
    waiting_time = State()


# Har bir foydalanuvchining yuborgan xabari
user_messages = {}


# =========================
# /start
# =========================

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):

    await state.clear()

    await message.answer(
        "👋 Salom!\n\n"
        "Menga kanalga joylanadigan matn, rasm yoki video yubor.\n"
        "Keyin qachon kanalga joylashni so‘rayman.\n\n"
        "Masalan:\n"
        "ertaga 20:00\n"
        "25-sentabr 20:00"
    )


# =========================
# VAQT KIRITISH
# BU HANDLER GENERIC HANDLERDAN OLDIN
# TURISHI MUHIM
# =========================

@dp.message(ScheduleState.waiting_time)
async def set_time(message: types.Message, state: FSMContext):

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
        # ERTAGA 20:00
        # =========================

        if text.startswith("ertaga"):

            time_text = text.replace("ertaga", "").strip()

            hour, minute = map(int, time_text.split(":"))

            send_time = now.replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0
            ) + timedelta(days=1)

        # =========================
        # 25-sentabr 20:00
        # =========================

        else:

            date_text, time_text = text.split()

            day = int(date_text.split("-")[0])
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
                "dekabr": 12,
            }

            if month_name not in months:
                raise ValueError("Oy noto‘g‘ri")

            month = months[month_name]

            hour, minute = map(int, time_text.split(":"))

            send_time = datetime(
                now.year,
                month,
                day,
                hour,
                minute,
                tzinfo=TZ
            )

            # Agar vaqt o‘tib ketgan bo‘lsa
            if send_time <= now:
                send_time = datetime(
                    now.year + 1,
                    month,
                    day,
                    hour,
                    minute,
                    tzinfo=TZ
                )

        # =========================
        # SAQLANGAN XABARNI OLISH
        # =========================

        original_message = user_messages.get(
            message.from_user.id
        )

        if not original_message:

            await message.answer(
                "❌ Avval kanalga yuboriladigan xabarni yubor."
            )

            await state.clear()
            return

        # =========================
        # SCHEDULER
        # =========================

        scheduler.add_job(
            send_to_channel,
            trigger=DateTrigger(run_date=send_time),
            args=[original_message],
        )

        await message.answer(
            "✅ Tayyor!\n\n"
            f"📅 Sana: {send_time.strftime('%d.%m.%Y')}\n"
            f"⏰ Vaqt: {send_time.strftime('%H:%M')}\n\n"
            "Xabar shu vaqtda kanalga joylanadi."
        )

        await state.clear()

    except Exception:

        await message.answer(
            "❌ Vaqt noto‘g‘ri yozildi.\n\n"
            "To‘g‘ri misollar:\n"
            "• ertaga 20:00\n"
            "• 25-sentabr 20:00"
        )


# =========================
# YANGI XABAR QABUL QILISH
# =========================

@dp.message()
async def receive_message(
    message: types.Message,
    state: FSMContext
):

    # Buyruqlarni o'tkazib yuboramiz
    if message.text and message.text.startswith("/"):
        return

    # Xabarni saqlash
    user_messages[message.from_user.id] = message

    # Vaqt so‘rash holatiga o'tish
    await state.set_state(
        ScheduleState.waiting_time
    )

    await message.answer(
        "📅 Qachon kanalga joylay?\n\n"
        "Masalan:\n"
        "• ertaga 20:00\n"
        "• 25-sentabr 20:00"
    )


# =========================
# KANALGA YUBORISH
# =========================

async def send_to_channel(message: types.Message):

    try:

        await bot.copy_message(
            chat_id=CHANNEL,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )

        print(
            f"✅ Xabar kanalga yuborildi: {CHANNEL}"
        )

    except Exception as e:

        print(
            f"❌ Kanalga yuborishda xatolik: {e}"
        )


# =========================
# BOTNI ISHGA TUSHIRISH
# =========================

async def main():

    print("🤖 Bot ishga tushmoqda...")

    scheduler.start()

    print("⏰ Scheduler ishga tushdi.")

    await dp.start_polling(bot)


# =========================
# START
# =========================

if __name__ == "__main__":
    asyncio.run(main())
