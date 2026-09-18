import os
import asyncio
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


# =====================================================
# ⚙️ SOZLAMALAR
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

TZ = ZoneInfo("Asia/Tashkent")

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


# =====================================================
# 🗂️ MA'LUMOTLAR
# =====================================================

# user_id -> kanal
user_channels = {}

# user_id -> post
user_messages = {}


# =====================================================
# 🔐 HOLATLAR
# =====================================================

class SetupState(StatesGroup):
    waiting_channel = State()
    waiting_confirmation = State()
    waiting_time = State()


# =====================================================
# 🚀 /START
# =====================================================

@dp.message(Command("start"))
async def start(
    message: types.Message,
    state: FSMContext
):

    await state.clear()

    user_id = message.from_user.id

    if user_id in user_channels:

        channel = user_channels[user_id]

        await message.answer(
            "🎉 <b>Xush kelibsiz!</b>\n\n"
            f"📢 Ulangan kanal: <b>{channel}</b>\n\n"
            "📨 Menga post yuboring.\n"
            "⏰ Keyin vaqtini so‘rayman.\n\n"
            "🚀 Boshladik!"
        )

    else:

        await message.answer(
            "👋 <b>Salom!</b> 🤖\n\n"
            "📢 Avval kanalingizni ulang.\n\n"
            "1️⃣ Botni kanalingizga administrator qiling.\n"
            "2️⃣ Kanal username'ini yuboring.\n\n"
            "💡 Masalan:\n"
            "<code>@meningkanalim</code>\n\n"
            "🔐 Men sizning ham administrator "
            "ekanligingizni tekshiraman."
        )

        await state.set_state(
            SetupState.waiting_channel
        )


# =====================================================
# 📢 KANALNI ULASH
# =====================================================

async def connect_channel(
    message: types.Message,
    state: FSMContext
):

    channel = (message.text or "").strip()

    if not channel.startswith("@"):

        await message.answer(
            "❌ <b>Kanal username noto‘g‘ri!</b>\n\n"
            "Username <code>@</code> bilan boshlanishi kerak.\n\n"
            "💡 Masalan:\n"
            "<code>@meningkanalim</code>"
        )
        return

    try:

        # 📢 Kanalni topish
        chat = await bot.get_chat(channel)

        # 👤 USER ADMINMI?
        user_member = await bot.get_chat_member(
            chat.id,
            message.from_user.id
        )

        if user_member.status not in [
            "administrator",
            "creator"
        ]:

            await message.answer(
                "🚫 <b>Kanal tasdiqlanmadi!</b>\n\n"
                "👤 Siz bu kanalning administratori emassiz.\n\n"
                "🔐 Faqat kanal administratori "
                "kanalni ulashi mumkin."
            )
            return

        # 🤖 BOT ADMINMI?
        bot_member = await bot.get_chat_member(
            chat.id,
            bot.id
        )

        if bot_member.status not in [
            "administrator",
            "creator"
        ]:

            await message.answer(
                "⚠️ <b>Bot kanal administratori emas!</b>\n\n"
                "📢 Avval botni kanalingizga "
                "administrator qilib qo‘shing."
            )
            return

        # 🔐 Tasdiqlash uchun vaqtinchalik saqlash
        await state.update_data(
            pending_channel=channel
        )

        await message.answer(
            "🔍 <b>1-BOSQICH MUVAFFAQIYATLI!</b> ✅\n\n"
            f"📢 Kanal: <code>{channel}</code>\n"
            "👤 Siz: <b>Administrator</b> ✅\n"
            "🤖 Bot: <b>Administrator</b> ✅\n\n"
            "🔐 <b>2-bosqich:</b>\n"
            "Kanalni ulash uchun:\n\n"
            "👉 <b>TASDIQLASH</b>\n\n"
            "deb yozing."
        )

        await state.set_state(
            SetupState.waiting_confirmation
        )

    except Exception as e:

        print("CHANNEL ERROR:", e)

        await message.answer(
            "❌ <b>Kanalni tekshirib bo‘lmadi!</b>\n\n"
            "🔎 Kanal username'ini tekshiring.\n\n"
            "💡 Masalan:\n"
            "<code>@meningkanalim</code>"
        )


# =====================================================
# 🔐 TASDIQLASH
# =====================================================

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
            "🔄 /start ni bosib qaytadan boshlang."
        )

        await state.clear()
        return

    try:

        chat = await bot.get_chat(channel)

        # 👤 USERNI QAYTA TEKSHIRISH
        user_member = await bot.get_chat_member(
            chat.id,
            message.from_user.id
        )

        # 🤖 BOTNI QAYTA TEKSHIRISH
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

        # ✅ SAQLASH
        user_channels[
            message.from_user.id
        ] = channel

        await state.clear()

        await message.answer(
            "🎉 <b>KANAL MUVAFFAQIYATLI ULANDI!</b> 🎉\n\n"
            f"📢 Kanal: <b>{channel}</b>\n"
            "👤 Siz: ✅ Administrator\n"
            "🤖 Bot: ✅ Administrator\n"
            "🔐 Tekshiruv: ✅ Muvaffaqiyatli\n\n"
            "📨 Endi post yuboring!\n\n"
            "📝 Matn\n"
            "📸 Rasm\n"
            "🎥 Video\n"
            "📄 Hujjat"
        )

    except Exception as e:

        print("CONFIRM ERROR:", e)

        await message.answer(
            "❌ <b>Tasdiqlashda xatolik!</b>\n\n"
            "🔄 Qaytadan urinib ko‘ring."
        )


# =====================================================
# 📨 POST SAQLASH
# =====================================================

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
        "⏰ Endi qachon kanalga joylay?\n\n"
        "💡 Masalan:\n\n"
        "🌙 <code>ertaga 20:00</code>\n"
        "📅 <code>18-sentabr 10:00</code>\n\n"
        "✍️ Vaqtni yozing."
    )


# =====================================================
# ⏰ VAQTNI TEKSHIRISH
# =====================================================

async def process_time(
    message: types.Message,
    state: FSMContext
):

    text = (message.text or "").lower().strip()

    now = datetime.now(TZ)

    try:

        # 🌙 ERTAGA 20:00
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

        # 📅 18-sentabr 10:00
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
                "dekabr": 12
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

            # Agar vaqt o'tgan bo'lsa
            if send_time <= now:

                await message.answer(
                    "⚠️ <b>Bu vaqt allaqachon o‘tib ketgan.</b>\n\n"
                    "⏰ Kelajakdagi vaqtni yozing.\n\n"
                    "Masalan:\n"
                    "<code>18-sentabr 12:00</code>"
                )
                return

        # 📦 POST
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
                "❌ Kanal ulanmagan.\n\n"
                "🔄 /start orqali kanalni ulang."
            )

            await state.clear()
            return

        # ⏰ JOB
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
            "🚀 Belgilangan vaqtda avtomatik yuboraman!"
        )

        await state.clear()

    except Exception as e:

        print("TIME ERROR:", e)

        await message.answer(
            "😅 <b>Vaqtni tushunmadim!</b>\n\n"
            "💡 To‘g‘ri yozing:\n\n"
            "🌙 <code>ertaga 20:00</code>\n"
            "📅 <code>18-sentabr 10:00</code>"
        )


# =====================================================
# 📨 BARCHA XABARLARNI BOSHQARISH
# =====================================================

@dp.message()
async def all_messages(
    message: types.Message,
    state: FSMContext
):

    current_state = await state.get_state()

    # =================================================
    # 🔐 KANAL ULASH
    # =================================================

    if current_state == SetupState.waiting_channel.state:

        await connect_channel(
            message,
            state
        )
        return

    # =================================================
    # 🔐 TASDIQLASH
    # =================================================

    if current_state == SetupState.waiting_confirmation.state:

        await confirm_channel(
            message,
            state
        )
        return

    # =================================================
    # ⏰ VAQT
    # =================================================

    if current_state == SetupState.waiting_time.state:

        await process_time(
            message,
            state
        )
        return

    # =================================================
    # 📨 YANGI POST
    # =================================================

    user_id = message.from_user.id

    if user_id not in user_channels:

        await message.answer(
            "🔒 <b>Avval kanalni ulang!</b>\n\n"
            "📢 Kanal username'ini yuboring.\n\n"
            "💡 Masalan:\n"
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


# =====================================================
# 📢 KANALGA YUBORISH
# =====================================================

async def send_to_channel(
    message: types.Message,
    channel: str
):

    try:

        await bot.copy_message(
            chat_id=channel,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )

        print(
            f"✅ POST YUBORILDI → {channel}"
        )

    except Exception as e:

        print(
            f"❌ POST YUBORILMADI → {channel}"
        )

        print(e)


# =====================================================
# 🤖 BOTNI ISHGA TUSHIRISH
# =====================================================

async def main():

    print("🤖 Bot ishga tushmoqda...")

    scheduler.start()

    print("⏰ Scheduler ishga tushdi.")

    await dp.start_polling(bot)


# =====================================================
# 🚀 START
# =====================================================

if __name__ == "__main__":

    asyncio.run(main())
