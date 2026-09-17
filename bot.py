import os
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = "@nothing_ls_forever"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")


class ScheduleState(StatesGroup):
    waiting_time = State()


user_messages = {}


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "Salom! Menga matn, rasm yoki video yubor.\n"
        "Keyin qachon kanalga joylashni so‘rayman."
    )


@dp.message()
async def receive_message(message: types.Message, state: FSMContext):
    if message.text and message.text.startswith("/"):
        return

    user_messages[message.from_user.id] = message
    await state.set_state(ScheduleState.waiting_time)

    await message.answer(
        "Qachon kanalga joylay?\n\n"
        "Misollar:\n"
        "ertaga 20:00\n"
        "25-sentabr 20:00"
    )


@dp.message(ScheduleState.waiting_time)
async def set_time(message: types.Message, state: FSMContext):
    text = message.text.lower().strip()
    now = datetime.now()

    try:
        if text.startswith("ertaga"):
            time_text = text.replace("ertaga", "").strip()
            hour, minute = map(int, time_text.split(":"))
            send_time = now.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            ) + timedelta(days=1)

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
                "oktabr": 10,
                "noyabr": 11,
                "dekabr": 12,
            }

            month = months[month_name]
            hour, minute = map(int, time_text.split(":"))

            send_time = datetime(
                now.year, month, day, hour, minute
            )

            if send_time < now:
                send_time = datetime(
                    now.year + 1, month, day, hour, minute
                )

        original_message = user_messages.get(message.from_user.id)

        if not original_message:
            await message.answer("Avval kanalga yuboriladigan xabarni yubor.")
            return

        scheduler.add_job(
            send_to_channel,
            trigger=DateTrigger(run_date=send_time),
            args=[original_message],
        )

        await message.answer(
            f"✅ Tayyor!\n"
            f"Xabar {send_time.strftime('%d.%m.%Y %H:%M')} da kanalga joylanadi."
        )

        await state.clear()

    except Exception:
        await message.answer(
            "Vaqt noto‘g‘ri yozildi.\n\n"
            "Masalan:\n"
            "ertaga 20:00\n"
            "25-sentabr 20:00"
        )


async def send_to_channel(message: types.Message):
    await bot.copy_message(
        chat_id=CHANNEL,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )


async def main():
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
