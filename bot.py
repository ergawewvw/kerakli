import os
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger


BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = os.getenv("CHANNEL", "@nothing_ls_forever")
TIMEZONE = ZoneInfo("Asia/Tashkent")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=TIMEZONE)

# Har bir foydalanuvchining yuborgan xabari saqlanadi
user_messages = {}


class ScheduleState(StatesGroup):
    waiting_time = State()


async def home(request):
    return web.Response(text="Telegram scheduler bot ishlayapti!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", home)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)

    await site.start()
    print(f"Web server {port}-portda ishga tushdi")


@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "Salom! 👋\n\n"
        "Menga matn, rasm yoki video yubor.\n"
        "Keyin qachon kanalga joylashni so‘rayman.\n\n"
        "Misollar:\n"
        "ertaga 20:00\n"
        "25-sentabr 20:00"
    )


@dp.message()
async def receive_message(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        return

    # Xabarni yuborgan chat va xabar ID sini saqlaymiz
    user_messages[message.from_user.id] = {
        "chat_id": message.chat.id,
        "message_id": message.message_id,
    }

    await state.set_state(ScheduleState.waiting_time)

    await message.answer(
        "Qachon kanalga joylay?\n\n"
        "Misollar:\n"
        "ertaga 20:00\n"
        "25-sentabr 20:00"
    )


@dp.message(ScheduleState.waiting_time)
async def set_time(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer(
            "Vaqtni matn ko‘rinishida yoz.\n"
            "Masalan: ertaga 20:00"
        )
        return

    text = message.text.lower().strip()
    now = datetime.now(TIMEZONE)

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

    try:
        if text.startswith("ertaga"):
            time_text = text.replace("ertaga", "").strip()
            hour, minute = map(int, time_text.split(":"))

            send_time = now.replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            ) + timedelta(days=1)

        else:
            date_text, time_text = text.split()
            day, month_name = date_text.split("-")

            day = int(day)
            month = months[month_name]
            hour, minute = map(int, time_text.split(":"))

            send_time = datetime(
                year=now.year,
                month=month,
                day=day,
                hour=hour,
                minute=minute,
                tzinfo=TIMEZONE,
            )

            if send_time < now:
                send_time = send_time.replace(year=now.year + 1)

        if send_time <= now:
            await message.answer("Bu vaqt o‘tib ketgan. Boshqa vaqt yoz.")
            return

        saved_message = user_messages.get(message.from_user.id)

        if not saved_message:
            await message.answer(
                "Avval kanalga yuboriladigan xabarni yubor."
            )
            return

        scheduler.add_job(
            send_to_channel,
            trigger=DateTrigger(run_date=send_time),
            args=[
                saved_message["chat_id"],
                saved_message["message_id"],
            ],
            misfire_grace_time=60,
        )

        await message.answer(
            "✅ Tayyor!\n\n"
            f"Xabar {send_time.strftime('%d.%m.%Y %H:%M')} da "
            "kanalga joylanadi."
        )

        await state.clear()

    except Exception:
        await message.answer(
            "Vaqt noto‘g‘ri yozildi.\n\n"
            "To‘g‘ri misollar:\n"
            "ertaga 20:00\n"
            "25-sentabr 20:00"
        )


async def send_to_channel(chat_id: int, message_id: int):
    try:
        await bot.copy_message(
            chat_id=CHANNEL,
            from_chat_id=chat_id,
            message_id=message_id,
        )

        print("Xabar kanalga yuborildi")

    except Exception as error:
        print(f"Xabar yuborishda xatolik: {error}")


async def main():
    await start_web_server()

    scheduler.start()

    print("Telegram bot ishga tushdi")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
