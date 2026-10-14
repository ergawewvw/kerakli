# Render deployment

Hosting sozlamalari: [RENDER.md](RENDER.md). Render uchun `python web.py`, mahalliy ishga tushirish uchun `python main.py`.

# Olimpiada Test Bot v4 — Word → Telegram Quiz (Groq AI)

9-, 10- va 11-sinflar uchun informatika olimpiadasi Telegram boti. `main.py` barcha avvalgi admin, profil, test, reyting va vaqt funksiyalarini saqlaydi; **`ai_import.py`** yangi Groq tahlilchisi.

## Eng muhim yangilik

Administrator `.docx` Word fayl yuboradi. Bot Groq vision modelidan foydalanib, undagi **savol matni va A/B/C/D variantlarini** aniqlaydi va haqiqiy Telegram Quiz poll'lariga mos formatga saqlaydi. Surat ko‘rinishidagi Word sahifalari ham (masalan, sahifalar JPG sifatida kiritilgan bo‘lsa) tahlil qilinadi. Savollardagi diagramma va jadval tushunarsiz bo‘lsa, asl Word fayli o‘quvchiga birga yuboriladi — AI natijasini tekshirish shart.

**Groq savol matnini ko‘chiradi, lekin javob kalitini ishonchli taxmin qilishiga tayanilmaydi.** Admin to‘g‘ri javoblar kalitini o‘zi kiritadi va tekshiradi. Agar AI barcha savollarni to‘liq ajrata olmasa, bot saqlashni to‘xtatadi va qo‘lda kiritishni taklif qiladi.

## O‘rnatish (Windows PowerShell, VS Code)

1. Ishlab turgan botni `Ctrl+C` bilan to‘xtating. **Eski `.env` va `data` papkangizni o‘chirmang.** Avval bazaning zaxira nusxasini oling.
2. Arxivdagi `main.py`, `db.py`, **`ai_import.py`** va `requirements.txt` fayllarini eski bot papkangizga ko‘chiring. `quiz_savollar_namuna.txt` ixtiyoriy.
3. Terminalda `python -m pip install -r requirements.txt` ni bajaring.
4. `.env` faylida bot tokeningiz va admin ID saqlangan bo‘lishi kerak. Quyidagi yangi parametrni ham qo‘shing:

    ```env
    GROQ_API_KEY=YANGI_MAXFIY_GROQ_KALITINGIZ
    ```

    Kalitni Groq konsolida oling. **Ilgari chatga yuborgan Groq kalitingizni bekor (revoke) qilib, yangisini yarating.** Kalitni hech kimga yubormang, `main.py` ichiga yozmang. Oldin oshkor qilingan Telegram bot tokenini ham BotFather orqali yangilang.
5. `python main.py` buyrug‘i bilan ishga tushiring.

## Yangi test yaratish

`/admin` → `➕ Test qo‘shish` → 9/10/11 sinf → test nomi → yil → muddat → **Word `.docx` faylini yuborish** → `🤖 AI orqali Quiz yaratish` → ajratilgan savollarni ko‘rish → **javoblar kalitini kiritish** (`A B C D ...`) → `💾 Saqlash` → testni ko‘rib chiqish → `✅ E’lon qilish`.

- Word fayl to‘liq Groq xizmatiga yuboriladi (rasmli sahifalar JPEG formatda). Uchinchi tomon AI servisiga yuborishni xohlamasangiz, `⌨️ Qo‘lda kiritish` tugmasidan foydalaning.
- Fayl 20 MB dan kichik, sahifa-rasmlar 20 ta yoki undan kam, savollar soni 1–100 ta bo‘lishi kerak.
- Bir nechta Word sahifasi bo‘ylab uzilgan kod, diagramma yoki jadvallar AI tomonidan noto‘g‘ri ko‘chirilishi mumkin; e’lon qilishdan oldin asl test bilan solishtiring.
- PDF, Excel, matn, rasm, video va boshqa turdagi fayllarni qo‘lda kalit bilan qo‘shish avvalgidek ishlaydi; **AI avtomatik import hozircha faqat DOCX uchun**.

## Eski Word testni Quizga aylantirish

`/admin` → `📚 Testlarni boshqarish` → kerakli Word test → `🤖 Groq AI: Word → Quiz` → ajratilgan savollar namunasi → `✅ Quizga saqlash`.

Bu amalda bazadagi oldingi javoblar kalitidan foydalaniladi. Topilgan savollar soni kalit bilan teng bo‘lishi va har savolda to‘rtta variant bo‘lishi kerak. Ma’lumotlar **tasdiq tugmasi bosilmaguncha** o‘zgarmaydi.

## O‘quvchi nima ko‘radi?

`/start` → sinfni tanlash → testni tanlash → boshlash. Telegram `type='quiz'` so‘rovnomasida har savol navbat bilan beriladi. Bot har bir javobni va natijani bazada saqlaydi. Savol yoki variant juda uzun bo‘lsa, to‘liq matn alohida xabar sifatida yuborilib, quizda A/B/C/D variantlari ko‘rsatiladi.

## Xavfsizlik, ishonchlilik va cheklovlar

- `GROQ_API_KEY` va `BOT_TOKEN` faqat `.env` faylida; `.gitignore` bu faylni Git'dan chetlatadi.
- AI javoblari ishonchli fakt emas; ular avtomatik tekshiriladi, ammo matndagi ko‘chirish xatolarini admin topishi kerak.
- Groq hisobingizdagi limit/narxlar qo‘llanadi, ularga mos ravishda import muvaffaqiyatsiz bo‘lishi mumkin.
- Import ishlashi uchun internet, mos Groq modeli va Groq kaliti kerak. Model o‘zgarsa `ai_import.py`dagi `MODEL` qiymatini Groq hujjatlariga qarab almashtiring.
- Telegram tokenlari bilan jonli integratsiya ushbu paketni tayyorlash muhitida sinovdan o‘tkazilmadi. Lokal sintaksis, rasmli Wordni aniqlash, JSON validatsiyasi va soxta AI javobi bilan oqim sinovdan o‘tkazildi.
