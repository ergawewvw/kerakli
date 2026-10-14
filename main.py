"""9–11-sinflar uchun Telegram Olimpiada test boti.

Savollar PDF, Word, rasm, video, audio, kod fayllari yoki oddiy matn
shaklida berilishi mumkin. Javob kalitini admin qo'lda kiritadi.
"""
from __future__ import annotations

import logging
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from telegram import (
    BotCommand, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup, Update,
)
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, PollAnswerHandler,
    ContextTypes, MessageHandler, filters,
)

import db
from ai_import import import_docx, validate_questions

load_dotenv(Path(__file__).with_name('.env'))
TOKEN = os.environ.get('BOT_TOKEN', '').strip()
ADMIN_IDS = {int(s.strip()) for s in os.environ.get('ADMIN_IDS', '').split(',') if s.strip().isdigit()}
DB_FILE = os.environ.get('DATABASE_PATH', 'data/olimpiada.sqlite3')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '').strip()

logging.basicConfig(
    format='%(asctime)s %(levelname)s %(name)s: %(message)s', level=logging.INFO,
)
logger = logging.getLogger(__name__)
# HTTP client INFO logs otherwise include Telegram API tokens in URLs.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

GRADES = (9, 10, 11)
LETTERS = 'ABCD'
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB, oddiy foydalanish uchun xavfsiz chegara
MAX_TEXT_CHARS = 12000
MAX_QUIZ_FILE_BYTES = 250 * 1024



def button(text: str, cb: str) -> Btn:
    return Btn(text, callback_data=cb)


def keys(*rows) -> Markup:
    return Markup([list(row) for row in rows])


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec='seconds')


def get_flow(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    return context.user_data.get('flow')


def clear_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop('flow', None)
    context.user_data.pop('draft', None)
    context.user_data.pop('quiz_edit_id', None)
    context.user_data.pop('ai_existing', None)


def set_flow(context: ContextTypes.DEFAULT_TYPE, name: str) -> None:
    context.user_data['flow'] = name


async def view(update: Update, text: str, markup: Markup | None = None) -> None:
    """Callback bo'lsa mavjud xabarni yangilaydi, aks holda yangi xabar."""
    if update.callback_query:
        q = update.callback_query
        try:
            await q.edit_message_text(text=text, reply_markup=markup)
            return
        except BadRequest as exc:
            if 'Message is not modified' in str(exc):
                return
            # Eski yoki media xabari bo'lishi mumkin, yangi xabar yuboramiz.
    if update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=markup)


def registration_buttons(prefix: str) -> Markup:
    return keys(
        (button('9-sinf', f'{prefix}:9'),),
        (button('10-sinf', f'{prefix}:10'),),
        (button('11-sinf', f'{prefix}:11'),),
    )


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = db.get_user(update.effective_user.id)
    if not user or user['age'] is None:
        await ask_age(update, context)
        return
    if user['grade'] not in GRADES:
        await view(update, '📚 Sinfingizni tanlang:', registration_buttons('grade'))
        return

    rows = [
        (button('📚 Testlarni tanlash', 'menu:tests'),),
        (button('📊 Mening natijalarim', 'menu:results'),),
        (button('🏆 Reyting', 'menu:ranking'),),
        (button('👤 Profil', 'menu:profile'),),
    ]
    if db.active_attempt(user['id']):
        rows.insert(1, (button('▶️ Testni davom ettirish', 'attempt:resume'),))
        rows.insert(2, (button('🏁 Testni yakunlash', 'finish_confirm:' + str(db.active_attempt(user['id'])['id'])),))
    if is_admin(user['id']):
        rows.append((button('🛠 Admin panel', 'admin:home'),))
    await view(update, f"🏠 Olimpiada Test Bot\n\n📖 Fan: Informatika\n🎓 Sinf: {user['grade']}\n\nKerakli bo'limni tanlang:", Markup(rows))


async def ask_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    set_flow(context, 'register_age')
    await view(update, "👋 Assalomu alaykum! Olimpiada testlariga xush kelibsiz.\n\n📝 Ro'yxatdan o'tish uchun yoshingizni raqam bilan yozing (masalan: 15).")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_flow(context)
    tg = update.effective_user
    db.upsert_user(tg.id, tg.first_name)
    await show_menu(update, context)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_flow(context)
    await show_menu(update, context)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_flow(context)
    await view(update, '✅ Amal bekor qilindi.')
    await show_menu(update, context)


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f'Sizning Telegram ID: {update.effective_user.id}\nBu raqamni .env ichidagi ADMIN_IDS ga kiriting (agar admin bo‘lsangiz).')


async def show_profile(update: Update) -> None:
    u = db.get_user(update.effective_user.id)
    if not u:
        await view(update, 'Avval /start buyrug‘ini bosing.')
        return
    await view(update, f"👤 Profil\n\nIsm: {u['name']}\nYosh: {u['age']}\nSinf: {u['grade']}\nID: {u['id']}",
               keys((button('🎓 Sinfni o‘zgartirish', 'profile:grade'),),
                    (button('🎂 Yoshni o‘zgartirish', 'profile:age'),),
                    (button('⬅️ Asosiy menyu', 'menu:home'),)))


async def show_tests(update: Update) -> None:
    u = db.get_user(update.effective_user.id)
    tests = db.tests_for_grade(u['grade']) if u else []
    if not tests:
        await view(update, "📭 Hozircha sinfingiz uchun testlar qo‘shilmagan. Keyinroq tekshiring.",
                   keys((button('⬅️ Bosh menyu', 'menu:home'),)))
        return
    rows = [(button(f"📝 {t['year']} · {t['title'][:36]} ({len(t['answer_key'])} savol)", f"test:{t['id']}"),)
            for t in tests[:35]]
    rows.append((button('⬅️ Bosh menyu', 'menu:home'),))
    await view(update, f"📚 {u['grade']}-sinf · Informatika\n\nTestni tanlang:", Markup(rows))


async def show_test_info(update: Update, test_id: int) -> None:
    t = db.get_test(test_id)
    u = db.get_user(update.effective_user.id)
    if not t or not t['published'] or not u or t['grade'] != u['grade']:
        await view(update, '⛔ Test topilmadi yoki sizning sinfingizga mos emas.')
        return
    await view(update,
               f"📄 {t['title']}\n🎓 {t['grade']}-sinf\n📆 Yil: {t['year']}\n📚 Fan: {t['subject']}\n"
               f"❓ Savollar: {len(t['answer_key'])}\n⏱ Vaqt: {t['duration']} daqiqa\n\n"
               "Boshlagach Telegram Quiz savollari ketma-ket yuboriladi. Agar savollar faylda bo‘lsa, material ham jo‘natiladi.",
               keys((button('🚀 Testni boshlash', f'begin:{test_id}'),),
                    (button('⬅️ Testlar', 'menu:tests'),)))


def remain(deadline: str) -> int:
    return max(0, int((datetime.fromisoformat(deadline) - now()).total_seconds()))


def parse_quiz_questions(text: str, key: str) -> list[dict]:
    """1. Savol\nA) variant ... D) variant formatidagi matnni tekshiradi."""
    questions = []
    item = None
    option = None
    for raw_line in text.replace('\r\n', '\n').split('\n'):
        line = raw_line.strip()
        if not line:
            continue
        num_match = re.match(r'^(\d{1,3})[.)]\s+(.+)$', line)
        opt_match = re.match(r'^([A-Da-d])[).:]\s*(.+)$', line)
        if num_match:
            if item is not None:
                questions.append(item)
            n = int(num_match.group(1))
            if n != len(questions) + 1:
                raise ValueError(f'Savol tartibi xato: {n}. Kutilgan: {len(questions)+1}.')
            item = {'q': num_match.group(2), 'options': {}}
            option = None
        elif opt_match:
            if item is None:
                raise ValueError('Dastlab 1. Savol matni kelishi kerak.')
            option = opt_match.group(1).upper()
            if option in item['options']:
                raise ValueError(f'{len(questions)+1}-savolda {option} ikki marta yozilgan.')
            item['options'][option] = opt_match.group(2)
        elif item is not None:
            if option is None:
                item['q'] += ' ' + line
            else:
                item['options'][option] += ' ' + line
        else:
            raise ValueError('Matn 1. Savol ... ko‘rinishida boshlanishi lozim.')
    if item is not None:
        questions.append(item)
    if len(questions) != len(key):
        raise ValueError(f'Javoblar kaliti {len(key)} ta, lekin savollar {len(questions)} ta.')
    for i, q in enumerate(questions, 1):
        if set(q['options']) != set(LETTERS):
            raise ValueError(f'{i}-savolda A, B, C va D variantlari to‘liq bo‘lishi kerak.')
        if len(q['q']) > 3500 or any(len(v) > 1500 for v in q['options'].values()):
            raise ValueError(f'{i}-savol yoki varianti juda uzun.')
        q['options'] = [q['options'][l] for l in LETTERS]
    if not questions:
        raise ValueError('Savollar topilmadi.')
    return questions


async def send_next_quiz(chat_id: int, attempt_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Telegramning haqiqiy non-anonymous Quiz poll'i orqali bitta savol yuboradi."""
    a = db.attempt(attempt_id)
    if not a or a['finished_at']:
        return
    if remain(a['deadline']) <= 0:
        await finish_and_announce(attempt_id, context, chat_id, timed_out=True)
        return
    if a['current_poll_id']:
        await context.bot.send_message(chat_id, '📝 Javob berilmagan Quiz yuqorida turibdi. O‘sha savolga javob bering.')
        return
    try:
        questions = json.loads(a['quiz_questions'] or '[]')
    except (ValueError, TypeError):
        questions = []
    idx = a['answers'].find('-')
    if idx == -1:
        await finish_and_announce(attempt_id, context, chat_id)
        return
    if idx < len(questions):
        item = questions[idx]
        question = item['q']
        choices = item['options']
        if len(question) <= 300 and all(len(option) <= 100 for option in choices):
            poll_prompt = f'{idx+1}. {question}' if len(question) + len(str(idx+1)) + 2 <= 300 else question
            poll_options = choices
        else:
            # Telegramning poll savoli/variantlarida belgilar cheklovi bor.
            full = f'❓ {idx+1}-savol:\n{question}\n\n' + '\n'.join(
                f'{letter}) {value}' for letter, value in zip(LETTERS, choices))
            for start in range(0, len(full), 3500):
                await context.bot.send_message(chat_id, full[start:start+3500])
            poll_prompt = f'{idx+1}-savol. To‘g‘ri javobni tanlang:'
            poll_options = list(LETTERS)
    else:
        poll_prompt = f'{idx+1}-savol. Yuborilgan materialdan foydalanib javob bering:'
        poll_options = list(LETTERS)
    try:
        message = await context.bot.send_poll(
            chat_id=chat_id,
            question=poll_prompt,
            options=poll_options,
            type='quiz',
            correct_option_id=LETTERS.index(a['answer_key'][idx]),
            is_anonymous=False,
            allows_multiple_answers=False,
        )
        stored = db.set_current_poll(attempt_id, idx, message.poll.id, message.message_id)
        if not stored:
            try:
                await context.bot.stop_poll(chat_id, message.message_id)
            except TelegramError:
                pass
    except TelegramError:
        logger.exception('Quiz yuborishda xatolik')
        await context.bot.send_message(chat_id, '⚠️ Quiz yuborilmadi. /menu orqali qayta urinib ko‘ring.')


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    poll = update.poll_answer
    if not poll or not poll.user or not poll.option_ids:
        return
    user_id = poll.user.id
    answer = db.quiz_poll_answer(poll.poll_id, user_id, poll.option_ids[0])
    if not answer:
        return  # Eskirgan yoki begona poll javobini e’tiborsiz qoldiramiz.
    aid, message_id = answer
    if message_id:
        try:
            await context.bot.stop_poll(user_id, message_id)
        except TelegramError:
            pass
    await send_next_quiz(user_id, aid, context)


async def send_source(chat_id: int, a, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Materialni saqlangan Telegram file_id orqali yuborish. Fayllarni ochmaydi/ishga tushirmaydi."""
    kind = a['media_kind'] or 'document'
    caption = (f"📎 {a['title']}\n{a['grade']}-sinf · {a['year']}\n"
               "Savollarga Telegram Quiz orqali javob bering.")
    try:
        if kind == 'text':
            material = a['source_text'] or ''
            await context.bot.send_message(chat_id, caption + '\n\n📝 Test savollari:')
            # Telegram xabari uzunligi 4096 belgidan oshmasligi lozim.
            for pos in range(0, len(material), 3500):
                await context.bot.send_message(chat_id, material[pos:pos + 3500])
        elif kind == 'photo':
            await context.bot.send_photo(chat_id, photo=a['file_id'], caption=caption)
        elif kind == 'video':
            await context.bot.send_video(chat_id, video=a['file_id'], caption=caption)
        elif kind == 'audio':
            await context.bot.send_audio(chat_id, audio=a['file_id'], caption=caption)
        elif kind == 'voice':
            await context.bot.send_voice(chat_id, voice=a['file_id'], caption=caption)
        else:
            await context.bot.send_document(chat_id, document=a['file_id'], caption=caption)
        return True
    except TelegramError:
        logger.exception('Test materialini yuborishda xatolik')
        await context.bot.send_message(chat_id, '⚠️ Test materialini yuborib bo‘lmadi. Adminga murojaat qiling.')
        return False


def schedule_timer(application: Application, a) -> None:
    if application.job_queue is None:
        raise RuntimeError('python-telegram-bot[job-queue] o‘rnatilmagan')
    name = f'attempt:{a["id"]}'
    for job in application.job_queue.get_jobs_by_name(name):
        job.schedule_removal()
    seconds = max(0, (datetime.fromisoformat(a['deadline']) - now()).total_seconds())
    application.job_queue.run_once(timer_expired, when=seconds, name=name,
                                   data={'attempt_id': a['id'], 'user_id': a['user_id']})


async def finish_and_announce(attempt_id: int, context: ContextTypes.DEFAULT_TYPE,
                              chat_id: int, timed_out: bool = False) -> bool:
    pending = db.attempt(attempt_id)
    if pending and pending['current_poll_message_id']:
        try:
            await context.bot.stop_poll(chat_id, pending['current_poll_message_id'])
        except TelegramError:
            pass
    score = db.finish_attempt(attempt_id, iso(now()))
    if score is None:
        return False
    if context.job_queue:
        for job in context.job_queue.get_jobs_by_name(f'attempt:{attempt_id}'):
            job.schedule_removal()
    a = db.attempt(attempt_id)
    if a is None:
        return False
    key = a['answer_key']
    total = len(key)
    missing = a['answers'].count('-')
    pct = score / total * 100
    overview = ' '.join(f"{i+1}{'✅' if x == y else '❌'}" for i, (x, y) in enumerate(zip(a['answers'], key)))
    solution = ' '.join(f'{i+1}-{letter}' for i, letter in enumerate(key))
    heading = '⌛ Vaqt tugadi!' if timed_out else '🏁 Test yakunlandi!'
    text = (f"{heading}\n\n📄 {a['title']}\n✅ To‘g‘ri: {score}/{total}\n"
            f"❌ Xato: {total-score-missing}\n⚪ Javobsiz: {missing}\n📊 Natija: {pct:.1f}%\n\n"
            f"📋 Savollar holati:\n{overview}\n\n🔑 To‘g‘ri javoblar:\n{solution}")
    try:
        await context.bot.send_message(chat_id, text, reply_markup=keys((button('🏠 Menyu', 'menu:home'),)))
    except Forbidden:
        logger.info('User botni bloklagan: %s', chat_id)
    return True


async def timer_expired(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    await finish_and_announce(data['attempt_id'], context, data['user_id'], timed_out=True)


async def show_results(update: Update) -> None:
    recent = db.recent_results(update.effective_user.id)
    if not recent:
        await view(update, '📊 Hozircha yakunlangan test yo‘q.', keys((button('⬅️ Menyu', 'menu:home'),)))
        return
    text = '📊 Oxirgi natijalaringiz:\n\n'
    for i, r in enumerate(recent, 1):
        total = len(r['answer_key'])
        text += f"{i}. {r['title']} ({r['grade']}-sinf, {r['year']}) — {r['score']}/{total} ({100*r['score']/total:.1f}%)\n"
    await view(update, text, keys((button('⬅️ Menyu', 'menu:home'),)))


async def show_ranking(update: Update) -> None:
    u = db.get_user(update.effective_user.id)
    board = db.leaderboard(u['grade']) if u else []
    text = f"🏆 {u['grade']}-sinf reytingi\n\n" if u else '🏆 Reyting\n\n'
    if not board:
        text += "Hozircha reytingda ishtirokchilar yo‘q."
    else:
        for i, r in enumerate(board, 1):
            text += f"{i}. {r['name'][:28]} — {r['avg_pct']:.1f}% ({r['total']} test)\n"
        text += '\nReyting: har bir test bo‘yicha eng yaxshi natijalarning o‘rtacha foizi.'
    await view(update, text, keys((button('⬅️ Menyu', 'menu:home'),)))


def admin_home_markup() -> Markup:
    return keys((button('➕ Test qo‘shish', 'admin:add'),),
                (button('📚 Testlarni boshqarish', 'admin:list'),),
                (button('📊 Statistika', 'admin:stats'),),
                (button('⬅️ Menyu', 'menu:home'),))


async def admin_home(update: Update) -> None:
    if not is_admin(update.effective_user.id):
        await view(update, '⛔ Sizda admin huquqi yo‘q.')
        return
    await view(update, '🛠 Administrator paneli\n\nTest materialini yuklash, javoblar kalitini kiritish va Telegram Quiz savollarini belgilash mumkin.', admin_home_markup())


async def admin_list(update: Update) -> None:
    tests = db.admin_tests()
    if not tests:
        await view(update, '📭 Hali test yo‘q.', keys((button('⬅️ Admin panel', 'admin:home'),)))
        return
    rows = [(button(f"{'🟢' if t['published'] else '⚪'} #{t['id']} · {t['grade']}-sinf · {t['title'][:28]}", f"admin:test:{t['id']}"),)
            for t in tests[:35]]
    rows.append((button('⬅️ Admin panel', 'admin:home'),))
    await view(update, '📚 Testlar (🟢 ochiq, ⚪ yopiq):', Markup(rows))


async def admin_test_detail(update: Update, test_id: int) -> None:
    t = db.get_test(test_id)
    if not t:
        await view(update, 'Test topilmadi.', keys((button('⬅️ Testlar', 'admin:list'),)))
        return
    await view(update,
               f"🛠 Test #{t['id']}\n{t['title']}\n{t['grade']}-sinf · {t['year']}\n"
               f"{len(t['answer_key'])} savol · {t['duration']} daqiqa\n"
               f"Holati: {'E’lon qilingan' if t['published'] else 'Yopiq'}\n"
               f"Quiz matni: {'✅ kiritilgan' if t['quiz_questions'] else '📎 material orqali'}",
               keys((button('🤖 Groq AI: Word → Quiz', f'admin:ai_existing:{test_id}'),),
                    (button('🧠 Quiz savollarini kiritish/tahrirlash', f'admin:quiz:{test_id}'),),
                    (button('🔒 Yopish' if t['published'] else '✅ E’lon qilish', f'admin:toggle:{test_id}'),),
                    (button('🗑 O‘chirish', f'admin:deleteask:{test_id}'),),
                    (button('⬅️ Testlar', 'admin:list'),)))


def ai_quiz_preview(items: list[dict]) -> str:
    result = []
    for i, item in enumerate(items[:2], 1):
        q = item['q'].replace('\n', ' ')
        result.append(f"{i}. {q[:170]}" + ('…' if len(q) > 170 else ''))
        for letter, option in zip(LETTERS, item['options']):
            option = option.replace('\n', ' ')
            result.append(f'{letter}) {option[:95]}' + ('…' if len(option) > 95 else ''))
    return '\n'.join(result)


async def ai_import_from_file(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              file_id: str, filename: str) -> list[dict] | None:
    if not GROQ_API_KEY:
        await update.effective_message.reply_text(
            '⚠️ AI ishlashi uchun .env fayliga GROQ_API_KEY=... kiriting va botni qayta ishga tushiring.')
        return None
    if not filename.lower().endswith('.docx'):
        await update.effective_message.reply_text('⚠️ Avtomatik Word → Quiz hozircha faqat .docx uchun.')
        return None
    await update.effective_message.reply_text(
        '🤖 Groq Word faylni tahlil qilyapti. Sahifa rasmlari bo‘lsa, ular ham AIga yuboriladi. '
        'Bu biroz vaqt olishi mumkin…')
    try:
        f = await context.bot.get_file(file_id)
        content = await f.download_as_bytearray()
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError('Hujjat 20 MB dan katta.')
        items = await import_docx(bytes(content), filename, GROQ_API_KEY)
        return items
    except ValueError as exc:
        await update.effective_message.reply_text(
            f'⚠️ Avtomatik ajratib bo‘lmadi: {exc}\n\n'
            'Word matnini tuzatib qayta urinib ko‘ring yoki Quizni matn/.txt orqali kiriting.')
    except Exception:
        logger.exception('Groq import xatosi')
        await update.effective_message.reply_text(
            '⚠️ AI servisi bilan bog‘lanishda xatolik bo‘ldi. Groq kaliti, model, internet '
            'va API limitini tekshiring. Qo‘lda kiritish ham ishlaydi.')
    return None


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    if not is_admin(update.effective_user.id):
        await view(update, '⛔ Ruxsat yo‘q.')
        return
    if data == 'admin:ai_new':
        draft = context.user_data.get('draft')
        if get_flow(context) != 'admin_ai_choice' or not draft or not draft.get('file_id'):
            await view(update, '⚠️ Jarayon eskirgan. /admin orqali qayta boshlang.')
            return
        items = await ai_import_from_file(update, context, draft['file_id'], draft['file_name'])
        if items is None:
            await view(update, '⌨️ Kalitni qo‘lda kiritishga o‘ting yoki Wordni qayta yuboring.',
                       keys((button('⌨️ Kalitni qo‘lda kiritish', 'admin:manual_key'),),
                            (button('❌ Bekor qilish', 'admin:discard'),)))
            return
        draft['ai_questions'] = items
        set_flow(context, 'admin_key')
        await view(update,
                   f'✅ Groq {len(items)} ta savol va ularning variantlarini ajratdi.\n\n'
                   f'🔎 Dastlabki 2 savol namunasi:\n{ai_quiz_preview([{"q": x["q"], "options": [x["options"][k] for k in LETTERS]} for x in items])}\n\n'
                   '⚠️ AI rasmlangan Wordda xato qilishi mumkin. Hujjat bilan solishtiring.\n'
                   '🔑 Endi barcha savollarning TO‘G‘RI javoblar kalitini yuboring, masalan: A B C D.\n'
                   '/cancel — bekor qilish')
        return
    if data == 'admin:manual_key':
        draft = context.user_data.get('draft')
        if not draft or not draft.get('file_id'):
            await view(update, '⚠️ Avval test faylini yuklang.')
            return
        draft.pop('ai_questions', None)
        set_flow(context, 'admin_key')
        await view(update, '🔑 Javoblar kalitini yuboring, masalan: A B C D.')
        return
    if data.startswith('admin:ai_existing:'):
        tid = int(data.rsplit(':', 1)[1])
        t = db.get_test(tid)
        if not t:
            await view(update, 'Test topilmadi.')
            return
        items = await ai_import_from_file(update, context, t['file_id'], t['file_name'])
        if items is None:
            return
        try:
            canonical = validate_questions(items, len(t['answer_key']))
        except ValueError as exc:
            await view(update, f'⚠️ AI savollarni to‘liq topmadi: {exc}\n'
                              'Quizni qo‘lda tuzating yoki Wordni tekshiring.',
                       keys((button('⬅️ Test', f'admin:test:{tid}'),)))
            return
        context.user_data['ai_existing'] = {'test_id': tid,
                                              'questions': json.dumps(canonical, ensure_ascii=False)}
        await view(update, f'🤖 {len(canonical)} ta savol Worddan ajratildi.\n\n'
                           f'🔎 Namuna:\n{ai_quiz_preview(canonical)}\n\n'
                           '⚠️ Javoblar kaliti ADMIN kiritgan kalitdan olinadi. '
                           'AI matni/variantlari xato bo‘lishi mumkin; tekshirmasdan e’lon qilmang.\n'
                           'Quyidagi tugma bosilmaguncha Quiz o‘zgarmaydi.',
                   keys((button('✅ Quizga saqlash', f'admin:ai_apply:{tid}'),),
                        (button('❌ Bekor qilish', f'admin:test:{tid}'),)))
        return
    if data.startswith('admin:ai_apply:'):
        tid = int(data.rsplit(':', 1)[1])
        pending = context.user_data.get('ai_existing')
        if not pending or pending['test_id'] != tid or not db.get_test(tid):
            await view(update, '⚠️ Import eskirgan, qayta boshlang.')
            return
        db.save_quiz_questions(tid, pending['questions'])
        context.user_data.pop('ai_existing', None)
        await view(update, f'✅ #{tid} testga Quiz savollari saqlandi. '
                           'Testni foydalanuvchilarga ochishdan oldin Word bilan solishtiring.',
                   keys((button('✏️ Qo‘lda tahrirlash', f'admin:quiz:{tid}'),),
                        (button('⬅️ Test', f'admin:test:{tid}'),)))
        return
    if data == 'admin:home':
        clear_flow(context)
        await admin_home(update)
    elif data == 'admin:add':
        clear_flow(context)
        context.user_data['draft'] = {}
        await view(update, '➕ Test qaysi sinfga tegishli?', registration_buttons('admin_grade'))
    elif data.startswith('admin_grade:'):
        try:
            grade = int(data.split(':')[1])
        except ValueError:
            return
        if grade not in GRADES or 'draft' not in context.user_data:
            await view(update, 'Jarayon eskirgan. Admin paneldan qayta boshlang.')
            return
        context.user_data['draft']['grade'] = grade
        set_flow(context, 'admin_title')
        await view(update, f'✅ {grade}-sinf tanlandi.\n\n📝 Test nomini yozing (masalan: Tuman olimpiadasi 1-variant):')
    elif data.startswith('admin:quiz:'):
        test_id = int(data.rsplit(':', 1)[1])
        test = db.get_test(test_id)
        if not test:
            await view(update, '⚠️ Test topilmadi.')
            return
        context.user_data['quiz_edit_id'] = test_id
        set_flow(context, 'admin_quiz_edit')
        await view(update,
                   f'🧠 Test #{test_id}: {len(test["answer_key"])} ta savol.\n\n'
                   'Quyidagi shaklda savollarni yuboring (uzunroq bo‘lsa UTF-8 .txt fayl yuboring):\n\n'
                   '1. Python tilida chop etish buyrug‘i qaysi?\n'
                   'A) print()\nB) input()\nC) len()\nD) range()\n\n'
                   '2. ...\nA) ...\nB) ...\nC) ...\nD) ...\n\n'
                   'Savollar soni javob kalitiga TENG bo‘lishi kerak.\n/cancel — bekor qilish')
    elif data == 'admin:nofile':
        draft = context.user_data.get('draft')
        if get_flow(context) != 'admin_file' or draft is None:
            await view(update, 'Jarayon eskirgan. /admin orqali qayta boshlang.')
            return
        draft.update(file_id='', media_kind='text', source_text='', file_name='')
        set_flow(context, 'admin_key')
        await view(update, '🧠 Quiz kalitini yozing (masalan: A B C D). Keyin savollarni kiritasiz.')
    elif data == 'admin:quiznew':
        if 'draft' not in context.user_data or 'key' not in context.user_data['draft']:
            await view(update, 'Avval yangi testni yarating.')
            return
        set_flow(context, 'admin_quiz_new')
        await view(update,
                   '🧠 Quiz savollari:\n\n1. Savol matni\nA) Birinchi variant\nB) Ikkinchi variant\n'
                   'C) Uchinchi variant\nD) To‘rtinchi variant\n\n'
                   'Keyingi savollar 2., 3. deb davom etadi. Matn yoki UTF-8 .txt fayl yuboring.\n'
                   'Savollar soni kalitdagi harflar soniga teng bo‘lsin.\n/cancel — bekor qilish')
    elif data == 'admin:list':
        await admin_list(update)
    elif data == 'admin:stats':
        users, tests, attempts = db.dashboard_stats()
        await view(update, f'📊 Statistika\n\n👥 Foydalanuvchilar: {users}\n📚 Testlar: {tests}\n✅ Yakunlangan urinishlar: {attempts}',
                   keys((button('⬅️ Admin panel', 'admin:home'),)))
    elif data.startswith('admin:test:'):
        await admin_test_detail(update, int(data.split(':')[2]))
    elif data.startswith('admin:toggle:'):
        tid = int(data.split(':')[2])
        if db.get_test(tid):
            db.toggle_test(tid)
        await admin_test_detail(update, tid)
    elif data.startswith('admin:deleteask:'):
        tid = int(data.split(':')[2])
        await view(update, f'⚠️ #{tid} testni butunlay o‘chirasizmi? Uning natijalari ham o‘chadi!',
                   keys((button('🗑 Ha, o‘chirish', f'admin:delete:{tid}'),),
                        (button('❌ Yo‘q', f'admin:test:{tid}'),)))
    elif data.startswith('admin:delete:'):
        db.delete_test(int(data.split(':')[2]))
        await view(update, '✅ Test o‘chirildi.', keys((button('⬅️ Testlar', 'admin:list'),)))
    elif data == 'admin:save':
        d = context.user_data.get('draft', {})
        if not all(k in d for k in ('grade', 'title', 'year', 'duration', 'file_id', 'key', 'media_kind')):
            await view(update, '⚠️ Ma’lumotlar to‘liq emas. Boshidan kiriting.', admin_home_markup())
            return
        if not d['file_id'] and not d.get('source_text') and not d.get('quiz_questions'):
            await view(update, '⚠️ Faylsiz test uchun avval Quiz savollarini kiriting.',
                       keys((button('🧠 Quiz savollarini kiritish', 'admin:quiznew'),),
                            (button('❌ Bekor qilish', 'admin:discard'),)))
            return
        tid = db.add_test(d['grade'], d['title'], d['year'], d['duration'],
                          d['file_id'], d['key'], d['media_kind'],
                          d.get('source_text', ''), d.get('file_name', ''))
        if d.get('quiz_questions'):
            db.save_quiz_questions(tid, d['quiz_questions'])
        clear_flow(context)
        await view(update, f'✅ Test #{tid} bazaga saqlandi.\n\nHozircha YOPIQ. Foydalanuvchilar ko‘rishi uchun uni e’lon qiling.',
                   keys((button('✅ E’lon qilish', f'admin:toggle:{tid}'),),
                        (button('⬅️ Admin panel', 'admin:home'),)))
    elif data == 'admin:discard':
        clear_flow(context)
        await admin_home(update)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or '').strip()
    flow = get_flow(context)
    uid = update.effective_user.id
    if flow == 'register_age' or flow == 'profile_age':
        if not text.isdigit() or not 12 <= int(text) <= 20:
            await update.message.reply_text('⚠️ Yoshni 12 dan 20 gacha butun raqam bilan yozing (masalan, 15).')
            return
        db.upsert_user(uid, update.effective_user.first_name)
        db.set_age(uid, int(text))
        clear_flow(context)
        user = db.get_user(uid)
        if user['grade'] not in GRADES:
            await update.message.reply_text('✅ Yoshingiz saqlandi. Endi sinfingizni tanlang:',
                                            reply_markup=registration_buttons('grade'))
        else:
            await update.message.reply_text('✅ Yoshingiz yangilandi.')
            await show_menu(update, context)
        return

    if flow in ('admin_quiz_edit', 'admin_quiz_new'):
        await store_quiz_text(update, context, text)
        return

    if flow and flow.startswith('admin_'):
        if not is_admin(uid):
            clear_flow(context)
            await update.message.reply_text('⛔ Ruxsat yo‘q.')
            return
        draft = context.user_data.get('draft')
        if draft is None:
            clear_flow(context)
            await update.message.reply_text('Jarayon eskirgan. /admin orqali qayta boshlang.')
            return
        if flow == 'admin_title':
            if not 3 <= len(text) <= 100:
                await update.message.reply_text('Test nomi 3–100 ta belgidan iborat bo‘lsin.')
                return
            draft['title'] = text
            set_flow(context, 'admin_year')
            await update.message.reply_text('📆 Olimpiada yilini yozing (masalan: 2025):')
        elif flow == 'admin_year':
            if not text.isdigit() or not 2000 <= int(text) <= 2100:
                await update.message.reply_text('⚠️ Yilni 2000–2100 oralig‘ida kiriting.')
                return
            draft['year'] = int(text)
            set_flow(context, 'admin_duration')
            await update.message.reply_text('⏱ Test davomiyligini daqiqada yozing (5–240):')
        elif flow == 'admin_duration':
            if not text.isdigit() or not 5 <= int(text) <= 240:
                await update.message.reply_text('⚠️ 5 dan 240 gacha daqiqa kiriting.')
                return
            draft['duration'] = int(text)
            set_flow(context, 'admin_file')
            await update.message.reply_text(
                '📎 Endi test materialini yuboring.\n\n'
                '• Fayl: PDF, DOCX, PPTX, XLSX, TXT, PY, CPP va boshqa hujjatlar\n'
                '• Rasm: JPG, PNG yoki Telegram rasmi\n'
                '• Video / audio / ovozli xabar\n'
                '• Yoki savollarni oddiy matn qilib yozing\n\n'
                '⚠️ Bir testga bitta fayl yoki bitta matn qabul qilinadi.\n'
                'Fayl hajmi 20 MB dan oshmasin.\n'
                'Faylsiz faqat Telegram Quiz yaratish uchun quyidagi tugmani bosing.\n'
                '/cancel — bekor qilish',
                reply_markup=keys((button('🧠 Faqat Quiz (faylsiz)', 'admin:nofile'),)))
        elif flow == 'admin_file':
            if not text or len(text) > MAX_TEXT_CHARS:
                await update.message.reply_text('⚠️ Matn 1–12000 belgidan iborat bo‘lishi kerak.')
                return
            draft['file_id'] = ''
            draft['media_kind'] = 'text'
            draft['source_text'] = text
            draft['file_name'] = ''
            await request_answer_key(update, context, 'Matn')
        elif flow == 'admin_key':
            cleaned = re.sub(r'[\s,;.|-]+', '', text).upper()
            if not cleaned or len(cleaned) > 100 or any(letter not in LETTERS for letter in cleaned):
                await update.message.reply_text('⚠️ Faqat A, B, C, D harflari. 1–100 savol. Misol: A B C D A yoki ABCDA')
                return
            if draft.get('ai_questions'):
                try:
                    checked = validate_questions(draft['ai_questions'], len(cleaned))
                except ValueError as exc:
                    await update.message.reply_text(f'⚠️ Kalit va AI savollari mos emas: {exc}\n'
                                                    'Kalitni qayta kiriting yoki /cancel orqali qayta import qiling.')
                    return
                draft['quiz_questions'] = json.dumps(checked, ensure_ascii=False)
            draft['key'] = cleaned
            clear = f"📋 Tasdiqlang:\n\n🎓 {draft['grade']}-sinf\n📄 {draft['title']}\n"
            clear += (f"📆 {draft['year']}\n⏱ {draft['duration']} daqiqa\n"
                      f"❓ {len(cleaned)} savol\n🔑 Javob kaliti: {cleaned}\n\n")
            if draft.get('quiz_questions'):
                clear += '🤖 AI savollari qo‘shildi. Matn/variantlarni Word bilan tekshiring.\n\n'
            clear += 'Materialdagi savollar soni va tartibi javoblar bilan bir xilmi?'

            set_flow(context, 'admin_confirm')
            await update.message.reply_text(clear, reply_markup=keys(
                (button('🧠 Quiz savollarini kiritish', 'admin:quiznew'),),
                (button('💾 Saqlash (yopiq holatda)', 'admin:save'),),
                (button('❌ Bekor qilish', 'admin:discard'),),
            ))
        elif flow == 'admin_confirm':
            await update.message.reply_text('Tasdiqlash uchun yuqoridagi tugmalardan foydalaning.')
        return

    await update.message.reply_text('Menyuni ochish uchun /menu yoki /start yozing.')


async def request_answer_key(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str) -> None:
    set_flow(context, 'admin_key')
    await update.effective_message.reply_text(
        f'✅ {label} qabul qilindi!\n\n'
        '🔑 Endi TO‘G‘RI JAVOBLAR KALITINI tartib bilan yuboring.\n'
        'Masalan, 5 savol uchun: A B C D A\n\n'
        'Har bir harf materialdagi bitta savolga mos keladi. '
        'Savollar fayldan avtomatik ajratilmaydi.')


async def store_quiz_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if not is_admin(update.effective_user.id):
        clear_flow(context)
        await update.effective_message.reply_text('⛔ Ruxsat yo‘q.')
        return
    edit_id = context.user_data.get('quiz_edit_id')
    draft = context.user_data.get('draft')
    editing = get_flow(context) == 'admin_quiz_edit'
    test = db.get_test(edit_id) if editing and edit_id is not None else None
    key = test['answer_key'] if editing and test else draft.get('key') if draft else None
    if not key:
        clear_flow(context)
        await update.effective_message.reply_text('⚠️ Jarayon eskirgan. Qayta boshlang.')
        return
    try:
        data = parse_quiz_questions(text, key)
    except ValueError as exc:
        await update.effective_message.reply_text(f'⚠️ Quiz formati xato: {exc}\nTuzatib qayta yuboring.')
        return
    encoded = json.dumps(data, ensure_ascii=False)
    if editing:
        db.save_quiz_questions(edit_id, encoded)
        context.user_data.pop('quiz_edit_id', None)
        clear_flow(context)
        await update.effective_message.reply_text(f'✅ {len(data)} ta Quiz savoli test #{edit_id}ga saqlandi.')
    else:
        draft['quiz_questions'] = encoded
        set_flow(context, 'admin_confirm')
        await update.effective_message.reply_text(
            f'✅ {len(data)} ta Quiz savoli tayyor!\nEndi testni saqlang:',
            reply_markup=keys((button('💾 Saqlash', 'admin:save'),),
                              (button('❌ Bekor qilish', 'admin:discard'),)))


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    flow = get_flow(context)
    if flow in ('admin_quiz_edit', 'admin_quiz_new') and update.message.document:
        if not is_admin(update.effective_user.id):
            await update.message.reply_text('⛔ Ruxsat yo‘q.')
            return
        document = update.message.document
        if not document.file_name or not document.file_name.lower().endswith('.txt'):
            await update.message.reply_text('⚠️ Quiz savollari uchun UTF-8 .txt fayl yuboring.')
            return
        if document.file_size and document.file_size > MAX_QUIZ_FILE_BYTES:
            await update.message.reply_text('⚠️ Matn fayli 250 KB dan kichik bo‘lishi kerak.')
            return
        try:
            f = await document.get_file()
            content = await f.download_as_bytearray()
            if len(content) > MAX_QUIZ_FILE_BYTES:
                raise ValueError('Fayl juda katta.')
            quiz_text = bytes(content).decode('utf-8-sig')
        except (TelegramError, UnicodeDecodeError, ValueError):
            await update.message.reply_text('⚠️ .txt faylni UTF-8 formatda yuboring.')
            return
        await store_quiz_text(update, context, quiz_text)
        return
    if flow != 'admin_file' or not is_admin(update.effective_user.id):
        await update.message.reply_text('Test materialini faqat /admin → “Test qo‘shish” orqali yuboring.')
        return
    draft = context.user_data.get('draft')
    if draft is None:
        clear_flow(context)
        await update.message.reply_text('Jarayon eskirgan. /admin orqali qayta boshlang.')
        return

    msg = update.effective_message
    if msg.document:
        media = msg.document
        kind = 'document'
        filename = media.file_name or 'hujjat'
        label = 'Hujjat'
    elif msg.photo:
        media = msg.photo[-1]
        kind, filename, label = 'photo', 'rasm', 'Rasm'
    elif msg.video:
        media = msg.video
        kind, filename, label = 'video', 'video', 'Video'
    elif msg.audio:
        media = msg.audio
        kind, filename, label = 'audio', 'audio', 'Audio'
    elif msg.voice:
        media = msg.voice
        kind, filename, label = 'voice', 'ovoz', 'Ovozli xabar'
    else:
        await msg.reply_text('⚠️ Bu media turi hozircha qo‘llab-quvvatlanmaydi.')
        return

    if media.file_size and media.file_size > MAX_UPLOAD_BYTES:
        await msg.reply_text('⚠️ Fayl 20 MB dan katta. Kichikroq fayl yuboring.')
        return
    # Hujjat kengaytmasini tekshirib cheklamaymiz: Telegram hujjat sifatida
    # yuborgan Word, Excel, kod, PDF va boshqa formatlar bir xil saqlanadi.
    draft['file_id'] = media.file_id
    draft['media_kind'] = kind
    draft['source_text'] = ''
    draft['file_name'] = filename[:200]
    if kind == 'document' and filename.lower().endswith('.docx'):
        set_flow(context, 'admin_ai_choice')
        await msg.reply_text(
            '📄 Word qabul qilindi!\n\n'
            '🤖 Groq AI Worddagi sahifa rasmlarini ham o‘qib, savollar va A/B/C/D '
            'variantlarini avtomatik Telegram Quizga tayyorlaydi.\n'
            '⚠️ Hujjat tarkibi tashqi Groq AI servisiga yuboriladi.\n'
            'AI xatolarini tekshirish va javoblar kalitini kiritish kerak.',
            reply_markup=keys((button('🤖 AI orqali Quiz yaratish', 'admin:ai_new'),),
                              (button('⌨️ Qo‘lda kiritish', 'admin:manual_key'),),
                              (button('❌ Bekor qilish', 'admin:discard'),)))
        return
    await request_answer_key(update, context, label)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data or ''
    uid = update.effective_user.id

    if data.startswith('admin:') or data.startswith('admin_grade:'):
        await handle_admin_callback(update, context, data)
        return

    # Dastlab ro'yxatdan o'tish talab qilinadi.
    user = db.get_user(uid)
    if not user:
        db.upsert_user(uid, update.effective_user.first_name)
        user = db.get_user(uid)
    if data.startswith('grade:'):
        try:
            grade = int(data.split(':')[1])
        except ValueError:
            return
        if grade not in GRADES:
            return
        if user['age'] is None:
            await ask_age(update, context)
            return
        db.set_grade(uid, grade)
        clear_flow(context)
        await show_menu(update, context)
        return
    if user['age'] is None or user['grade'] not in GRADES:
        await show_menu(update, context)
        return

    if data == 'menu:home':
        clear_flow(context)
        await show_menu(update, context)
    elif data == 'menu:tests':
        await show_tests(update)
    elif data == 'menu:results':
        await show_results(update)
    elif data == 'menu:ranking':
        await show_ranking(update)
    elif data == 'menu:profile':
        await show_profile(update)
    elif data == 'profile:grade':
        await view(update, '🎓 Yangi sinfingizni tanlang:', registration_buttons('grade'))
    elif data == 'profile:age':
        set_flow(context, 'profile_age')
        await view(update, '🎂 Yangi yoshingizni raqam bilan yozing:')
    elif data.startswith('test:'):
        await show_test_info(update, int(data.split(':')[1]))
    elif data.startswith('begin:'):
        test_id = int(data.split(':')[1])
        existing = db.active_attempt(uid)
        if existing:
            await view(update, '⚠️ Sizda yakunlanmagan test bor. Avval uni tugating.',
                       keys((button('▶️ Davom ettirish', 'attempt:resume'),),
                            (button('⬅️ Menyu', 'menu:home'),)))
            return
        t = db.get_test(test_id)
        if not t or not t['published'] or t['grade'] != user['grade']:
            await view(update, '⛔ Bu test mavjud emas yoki sinfingizga mos emas.')
            return
        started = now()
        deadline = started + timedelta(minutes=t['duration'])
        aid = db.create_attempt(uid, test_id, len(t['answer_key']), iso(started), iso(deadline))
        a = db.attempt(aid)
        schedule_timer(context.application, a)
        if a['media_kind'] != 'text' or not a['quiz_questions']:
            await send_source(update.effective_chat.id, a, context)
        await send_next_quiz(uid, aid, context)
    elif data == 'attempt:resume':
        a = db.active_attempt(uid)
        if not a:
            await view(update, 'Yakunlanmagan test mavjud emas.')
        elif remain(a['deadline']) <= 0:
            await finish_and_announce(a['id'], context, uid, timed_out=True)
            await show_menu(update, context)
        else:
            await send_next_quiz(uid, a['id'], context)
    elif data.startswith('source:') or data.startswith('pdf:'):
        aid = int(data.split(':')[1])
        a = db.attempt(aid)
        if a and a['user_id'] == uid and a['finished_at'] is None:
            await send_source(update.effective_chat.id, a, context)
    elif data.startswith(('grid:', 'go:', 'nav:', 'answer:')):
        # Old inline A/B/C/D buttons must not bypass the new Quiz poll flow.
        a = db.attempt(int(data.split(':')[1]))
        if a and a['user_id'] == uid and not a['finished_at']:
            await send_next_quiz(uid, a['id'], context)
        else:
            await view(update, 'Test yakunlangan yoki topilmadi.')
    elif data.startswith('finish_confirm:'):
        aid = int(data.split(':')[1])
        a = db.attempt(aid)
        if not a or a['user_id'] != uid or a['finished_at']:
            await view(update, 'Test topilmadi yoki allaqachon yakunlangan.')
            return
        missing = a['answers'].count('-')
        await view(update, f"🏁 Haqiqatan testni yakunlaysizmi?\n\n⚪ Javobsiz savollar: {missing}\nYakunlangach javoblarni o‘zgartirib bo‘lmaydi.",
                   keys((button('✅ Ha, yakunlash', f'finish:{aid}'),),
                        (button('↩️ Testga qaytish', 'attempt:resume'),)))
    elif data.startswith('finish:'):
        aid = int(data.split(':')[1])
        a = db.attempt(aid)
        if not a or a['user_id'] != uid:
            await view(update, '⛔ Ruxsat yo‘q.')
            return
        if a['finished_at']:
            await view(update, 'Bu test allaqachon yakunlangan.')
            return
        await finish_and_announce(aid, context, uid, timed_out=remain(a['deadline']) <= 0)
        await show_menu(update, context)


async def finish_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    a = db.active_attempt(update.effective_user.id)
    if not a:
        await update.effective_message.reply_text('Yakunlanmagan test yo‘q.')
        return
    await update.effective_message.reply_text(
        f'Testni yakunlaysizmi? Javobsiz: {a["answers"].count("-")}',
        reply_markup=keys((button('✅ Ha, yakunlash', f'finish:{a["id"]}'),),
                          (button('▶️ Davom ettirish', 'attempt:resume'),)))


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_flow(context)
    await admin_home(update)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error('Bot xatosi', exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(update.effective_chat.id, '⚠️ Texnik xatolik yuz berdi. /menu orqali qayta urinib ko‘ring.')
        except TelegramError:
            pass


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand('start', 'Botni boshlash'),
        BotCommand('menu', 'Asosiy menyu'),
        BotCommand('id', 'Telegram IDni ko‘rish'),
        BotCommand('cancel', 'Amalni bekor qilish'),
        BotCommand('finish', 'Testni yakunlash'),
        BotCommand('admin', 'Admin panel (adminlar uchun)'),
    ])
    # Restartdan keyin ham barcha faol taymerlarni tiklash.
    for row in db.unfinished_attempts():
        a = db.attempt(row['id'])
        if a:
            if remain(a['deadline']) <= 0:
                # Bot o'chirilgan paytda muddat o'tgan bo'lsa ham natija saqlanadi.
                await finish_and_announce(a['id'], app, a['user_id'], timed_out=True)
            else:
                schedule_timer(app, a)


def build_application(*, webhook: bool = False) -> Application:
    if not TOKEN or TOKEN == 'YOUR_TELEGRAM_BOT_TOKEN':
        raise SystemExit('BOT_TOKEN topilmadi. .env fayliga bot tokenini yozing.')
    from persistence import SessionPersistence
    builder = (ApplicationBuilder().token(TOKEN).post_init(post_init)
               .concurrent_updates(False).persistence(SessionPersistence()))
    if webhook:
        builder = builder.updater(None)
    app = builder.build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('menu', menu_command))
    app.add_handler(CommandHandler('cancel', cancel))
    app.add_handler(CommandHandler('id', my_id))
    app.add_handler(CommandHandler('admin', admin_command))
    app.add_handler(CommandHandler('finish', finish_command))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    app.add_handler(MessageHandler(
        (filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE)
        & filters.ChatType.PRIVATE, handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_text))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    db.configure(DB_FILE)
    db.init_db()
    app = build_application()
    logger.info('Bot ishga tushyapti...')
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == '__main__':
    main()
