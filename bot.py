import os
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger


# =========================================================
# ⚙️ SOZLAMALAR
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

TZ = ZoneInfo("Asia/Tashkent")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

scheduler = AsyncIOScheduler(timezone=TZ)


# =========================================================
# 🗂️ VAQTINCHALIK MA'LUMOTLAR
# =========================================================

# user_id -> kanal
user_channels = {}

# user_id -> yuborgan post
user_messages = {}


# =========================================================
# 🔐 HOLATLAR
# =========================================================

class SetupState(StatesGroup):
    waiting_channel = State()
    waiting_confirmation = State()
    waiting_post = State()
    waiting_time = State()


# =========================================================
# 🚀 /START
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
            "📨 Endi menga post yuborishingiz mumkin.\n"
            "⏰ Keyin joylash vaqtini so‘rayman.\n\n"
            "🚀 Boshlayveramiz!"
        )

    else:

        await message.answer(
            "👋 <b>Salom!</b> 🤖\n\n"
            "📢 Botdan foydalanish uchun avval "
            "kanalingizni ulang.\n\n"
            "🔹 <b>1-bosqich:</b> Botni kanalingizga "
            "administrator qilib qo‘shing.\n\n"
            "🔹 <b>2-bosqich:</b> Kanal username'ini yuboring.\n\n"
            "💡 Masalan:\n"
            "<code>@meningkanalim</code>\n\n"
            "🔐 Keyin sizning ham kanal administratori "
            "ekanligingizni tekshiraman."
        )

        await state.set_state(
            SetupState.waiting_channel
        )


# =========================================================
# 📢 KANALNI QABUL QILISH
# =========================================================

@dp.message(SetupState.waiting_channel, F.text)
async def connect_channel(
    message: types.Message,
    state: FSMContext
):

    channel = message.text.strip()

    if not channel.startswith("@"):

        await message.answer(
            "❌ <b>Kanal username noto‘g‘ri!</b>\n\n"
            "Username <code>@</code> bilan boshlanishi kerak.\n\n"
            "💡 Masalan:\n"
            "<code>@meningkanalim</code>"
        )
        return

    try:

        # =================================================
        # 1️⃣ KANALNI TOPISH
        # =================================================

        chat = await bot.get_chat(channel)

        # =================================================
        # 2️⃣ FOYDALANUVCHINI TEKSHIRISH
        # =================================================

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
                "Siz bu kanalning administratori emassiz.\n\n"
                "🔐 Faqat kanal administratori "
                "kanalni ulashi mumkin.\n\n"
                "📢 O‘zingiz admin bo‘lgan kanalni yuboring."
            )
            return

        # =================================================
        # 3️⃣ BOTNI TEKSHIRISH
        # =================================================

        bot_member = await bot.get_chat_member(
            chat.id,
            bot.id
        )

        if bot_member.status not in [
            "administrator",
            "creator"
        ]:

            await message.answer(
                "⚠️ <b>Bot hali kanal administratori emas!</b>\n\n"
                f"📢 Kanal: <code>{channel}</code>\n\n"
                "1️⃣ Kanal sozlamalarini oching.\n"
                "2️⃣ Administrators bo‘limiga kiring.\n"
                "3️⃣ Botni administrator qilib qo‘shing.\n"
                "4️⃣ Keyin kanalni qayta yuboring.\n\n"
                "🔒 Shundan keyin xavfsizlik tekshiruvidan o‘tamiz."
            )
            return

        # =================================================
        # 4️⃣ TASDIQLASHGA TAYYOR
        # =================================================

        await state.update_data(
            pending_channel=channel
        )

        await message.answer(
            "🔍 <b>1-bosqich muvaffaqiyatli!</b> ✅\n\n"
            f"📢 Kanal: <code>{channel}</code>\n"
            "👤 Siz: <b>Administrator</b> ✅\n"
            "🤖 Bot: <b>Administrator</b> ✅\n\n"
            "🔐 Endi kanalni ulash uchun:\n\n"
            "👉 <b>TASDIQLASH</b> deb yuboring."
        )

        await state.set_state(
            SetupState.waiting_confirmation
        )

    except Exception as e:

        print(f"CHANNEL ERROR: {e}")

        await message.answer(
            "❌ <b>Kanalni tekshirishda xatolik!</b>\n\n"
            "🔎 Quyidagilarni tekshiring:\n"
            "• Kanal username'i to‘g‘rimi?\n"
            "• Kanal publicmi?\n"
            "• Bot kanalga admin qilib qo‘shilganmi?\n\n"
            "💡 Masalan:\n"
            "<code>@meningkanalim</code>"
        )


# =========================================================
# 🔐 2-BOSQICH TASDIQLASH
# =========================================================

@dp.message(SetupState.waiting_confirmation, F.text)
async def confirm_channel(
    message: types.Message,
    state: FSMContext
):

    text = message.text.lower().strip()

    if text not in [
        "tasdiqlash",
        "tasdiqlayman",
        "ha"
    ]:

        await message.answer(
            "🔐 <b>Tasdiqlash kerak!</b>\n\n"
            "Kanalni ulash uchun:\n"
            "👉 <b>TASDIQLASH</b> deb yozing."
        )
        return

    data = await state.get_data()

    channel = data.get("pending_channel")

    if not channel:

        await message.answer(
            "❌ Tasdiqlash ma'lumoti topilmadi.\n\n"
            "🔄 /start ni bosib qaytadan boshlang."
        )

        await state.clear()
        return

    try:

        chat = await bot.get_chat(channel)

        # Foydalanuvchini yana bir marta tekshiramiz
        user_member = await bot.get_chat_member(
            chat.id,
            message.from_user.id
        )

        # Botni ham yana tekshiramiz
        bot_member = await bot.get_chat_member(
            chat.id,
            bot.id
        )

        if user_member.status not in [
            "administrator",
            "creator"
        ]:

            await message.answer(
                "🚫 <b>Tasdiqlash bekor qilindi!</b>\n\n"
                "Siz kanal administratori emassiz."
            )
            return

        if bot_member.status not in [
            "administrator",
            "creator"
        ]:

            await message.answer(
                "🤖 Bot kanal administratori emas.\n\n"
                "Botga administrator huquqini bering."
            )
            return

        # =================================================
        # ✅ KANALNI SAQLASH
        # =================================================

        user_channels[
            message.from_user.id
        ] = channel

        await state.clear()

        await message.answer(
            "🎉🎉 <b>KANAL MUVAFFAQIYATLI ULANDI!</b> 🎉🎉\n\n"
            f"📢 Kanal: <b>{channel}</b>\n"
            "👤 Siz: ✅ Admin\n"
            "🤖 Bot: ✅ Admin\n"
            "🔐 Xavfsizlik: ✅ Tasdiqlandi\n\n"
            "🚀 Endi menga post yuboring!\n\n"
            "📸 Rasm\n"
            "🎥 Video\n"
            "📝 Matn\n\n"
            "⏰ Keyin qachon joylashni so‘rayman."
        )

    except Exception as e:

        print(f"CONFIRM ERROR: {e}")

        await message.answer(
            "❌ Tasdiqlashda xatolik yuz berdi.\n\n"
            "🔄 Qaytadan urinib ko‘ring."
        )


# =========================================================
# 📨 POST QABUL QILISH
# =========================================================

@dp.message()
async def receive_message(
    message: types.Message,
    state: FSMContext
):

    # Buyruqlarni o'tkazib yuborish
    if message.text and message.text.startswith("/"):
        return

    user_id = message.from_user.id

    # =====================================================
    # 🔒 KANAL ULANGANMI?
    # =====================================================

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

    # =====================================================
    # 📨 POSTNI SAQLASH
    # =====================================================

    user_messages[user_id] = message

    await state.set_state(
        SetupState.waiting_time
    )

    await message.answer(
        "📨 <b>Post qabul qilindi!</b> ✅\n\n"
        "⏰ Endi qachon kanalga joylay?\n\n"
        "💡 Misollar:\n\n"
        "🌙 <code>ertaga 20:00</code>\n"
        "📅 <code>25-sentabr 20:00</code>"
    )


# =========================================================
# ⏰ VAQTNI QABUL QILISH
# =========================================================

@dp.message(SetupState.waiting_time, F.text)
async def set_time(
    message: types.Message,
    state: FSMContext
):

    text = message.text.lower().strip()

    now = datetime.now(TZ)

    try:

        # =================================================
        # 🌙 ERTAGA
        # =================================================

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

        # =================================================
        # 📅 SANA
        # =================================================

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

        # =================================================
        # 📦 POSTNI OLISH
        # =================================================

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
            return

        if not channel:

            await message.answer(
                "🔒 Kanal ulanmagan.\n\n"
                "🔄 /start orqali kanalni ulang."
            )

            await state.clear()
            return

        # =================================================
        # ⏰ SCHEDULER
        # =================================================

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
            "🎉 <b>POST REJALASHTIRILDI!</b> 🎉\n\n"
            f"📢 Kanal: <b>{channel}</b>\n"
            f"📅 Sana: <b>{send_time.strftime('%d.%m.%Y')}</b>\n"
            f"⏰ Vaqt: <b>{send_time.strftime('%H:%M')}</b>\n\n"
            "🚀 Belgilangan vaqtda avtomatik yuboraman."
        )

        await state.clear()

    except Exception:

        await message.answer(
            "😅 <b>Vaqtni tushunmadim.</b>\n\n"
            "💡 Shunday yozing:\n\n"
            "🌙 <code>ertaga 20:00</code>\n"
            "📅 <code>25-sentabr 20:00</code>"
        )


# =========================================================
# 📢 KANALGA YUBORISH
# =========================================================

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
            f"✅ POST YUBORILDI → {channel}"
        )

    except Exception as e:

        print(
            f"❌ POST YUBORISHDA XATO → {channel}"
        )

        print(e)


# =========================================================
# 🤖 BOTNI ISHGA TUSHIRISH
# =========================================================

async def main():

    print("🤖 Bot ishga tushmoqda...")

    scheduler.start()

    print("⏰ Scheduler ishga tushdi.")

    await dp.start_polling(bot)


# =========================================================
# 🚀 START
# =========================================================

if __name__ == "__main__":
    asyncio.run(main())
