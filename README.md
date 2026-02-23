<a id="english-guide"></a>
# PIMX PLAY BOT 🎮🤖

A production-style Telegram bot for app discovery, category browsing, and controlled file delivery.
It combines local catalog data with live provider search, then serves results through a clean inline-button workflow.

[![Persian Description](https://img.shields.io/badge/Read-Persian%20Description-0A66C2?style=for-the-badge)](#persian-description)

## What This Bot Does ✨
- Lets users search apps quickly with `🔍` flow
- Shows curated categories with `📁` flow
- Aggregates results from multiple Android app sources
- Provides version-aware result grouping and pagination
- Delivers files with temporary storage and auto-cleanup
- Enforces required channel membership before usage
- Includes admin shortcuts for user stats and user list

## Search Sources 🌐
- Local in-code app database
- Aptoide
- F-Droid
- OpenAPK
- APKMirror
- IzzyOnDroid-style source integration

## User Experience Flow 🧭
1. User starts bot (`/start`)
2. Bot checks channel membership
3. User selects `Search`, `Categories`, or `Help`
4. Bot shows paginated inline results
5. User selects app/version
6. Bot downloads and sends file
7. Temporary file gets deleted automatically after send window

## Commands & UI 📌
- `/start` start panel and membership flow
- `/help` usage guide
- Text keyboard shortcuts for search, categories, and help
- Inline callbacks for pagination, category selection, and new search

## Admin Features 🛡️
- User count statistics
- User list preview
- Admin-only visibility for management actions

## Tech Stack 🛠️
- Python
- `python-telegram-bot`
- `aiohttp`
- `asyncio`
- JSON-based user persistence (`users_db.json`)

## Configuration ⚙️
Important constants are currently defined directly in `main.py`:
- `TOKEN`
- `ADMIN_CHAT_ID`
- `CHANNEL_USERNAME` / `CHANNEL_URL`
- `USERS_DB_FILE`
- `DELETE_AFTER_SEND_SECONDS`

Recommended production setup:
- Move token and admin/channel values to environment variables
- Keep logs and temp files outside version-controlled directories

## Local Run 🚀
```bash
pip install -r requirements.txt
python main.py
```

## Repository Structure 📂
- `main.py`: main bot runtime and handlers
- `requirements.txt`: dependencies
- `users_db.json`: runtime user store (created/updated during execution)
- `downloads/` and temp files: transient file outputs

## Reliability Notes 🔧
- Async network operations for responsive interactions
- Cache cleanup routines for search/size data
- Retry-safe style message editing/deleting around Telegram callbacks

## Security Notes 🔐
- Never commit real bot tokens in public repos
- Rotate token immediately if exposed
- Restrict admin IDs and validate channel checks

## Project Goal 🎯
Build a fast, practical, and maintainable Telegram app-search bot with clean user flow and controlled delivery lifecycle.

---

<a id="persian-description"></a>
# 🇮🇷 راهنمای فارسی (ترجمه کامل)

[![US Back to English](https://img.shields.io/badge/US-Back%20to%20English-0A2540?style=for-the-badge)](#english-guide)

# ربات PIMX PLAY 🎮🤖

یک ربات تلگرامی در سطح پروداکشن برای کشف اپلیکیشن، مرور دسته‌بندی‌ها، و تحویل کنترل‌شده فایل.
این بات داده‌های کاتالوگ محلی را با جستجوی زنده از چند ارائه‌دهنده ترکیب می‌کند و نتیجه را با جریان دکمه‌ای منظم نمایش می‌دهد.

## این بات چه کار می‌کند ✨
- جستجوی سریع برنامه‌ها با مسیر `🔍`
- نمایش دسته‌بندی‌های آماده با مسیر `📁`
- تجمیع نتیجه از چند منبع اپ اندروید
- گروه‌بندی نسخه‌محور نتایج همراه با صفحه‌بندی
- ارسال فایل با فضای موقت و پاک‌سازی خودکار
- اعمال شرط عضویت کانال قبل از استفاده
- میانبرهای ادمین برای آمار کاربران و لیست کاربران

## منابع جستجو 🌐
- دیتابیس محلی داخل کد
- Aptoide
- F-Droid
- OpenAPK
- APKMirror
- یکپارچه‌سازی منبع سبک IzzyOnDroid

## جریان تجربه کاربر 🧭
1. کاربر بات را شروع می‌کند (`/start`)
2. بات عضویت کانال را بررسی می‌کند
3. کاربر یکی از `جستجو`، `دسته‌بندی‌ها` یا `راهنما` را انتخاب می‌کند
4. بات نتایج صفحه‌بندی‌شده را با دکمه‌های inline نشان می‌دهد
5. کاربر اپ/نسخه را انتخاب می‌کند
6. بات فایل را دانلود و ارسال می‌کند
7. فایل موقت بعد از بازه ارسال به‌صورت خودکار حذف می‌شود

## دستورات و رابط 📌
- `/start` پنل شروع و جریان عضویت
- `/help` راهنمای استفاده
- میانبرهای کیبورد متنی برای جستجو، دسته‌بندی‌ها و راهنما
- کال‌بک‌های inline برای صفحه‌بندی، انتخاب دسته و جستجوی جدید

## امکانات ادمین 🛡️
- آمار تعداد کاربران
- پیش‌نمایش لیست کاربران
- نمایش مدیریت فقط برای ادمین

## پشته فنی 🛠️
- Python
- `python-telegram-bot`
- `aiohttp`
- `asyncio`
- نگهداری کاربران با JSON (`users_db.json`)

## تنظیمات ⚙️
ثابت‌های مهم فعلاً مستقیم داخل `main.py` تعریف شده‌اند:
- `TOKEN`
- `ADMIN_CHAT_ID`
- `CHANNEL_USERNAME` / `CHANNEL_URL`
- `USERS_DB_FILE`
- `DELETE_AFTER_SEND_SECONDS`

پیشنهاد برای محیط پروداکشن:
- انتقال توکن و مقادیر ادمین/کانال به متغیرهای محیطی
- نگهداری لاگ‌ها و فایل‌های موقت خارج از مسیرهای نسخه‌گذاری

## اجرای محلی 🚀
```bash
pip install -r requirements.txt
python main.py
```

## ساختار ریپو 📂
- `main.py`: هسته اصلی بات و هندلرها
- `requirements.txt`: وابستگی‌ها
- `users_db.json`: ذخیره کاربران در زمان اجرا
- `downloads/` و فایل‌های موقت: خروجی‌های گذرا

## نکات پایداری 🔧
- عملیات شبکه async برای پاسخ‌گویی بهتر
- روتین‌های پاک‌سازی کش جستجو/اندازه
- ویرایش/حذف پیام با سبک امن در کال‌بک‌های تلگرام

## نکات امنیتی 🔐
- توکن واقعی بات را در ریپوی عمومی commit نکنید
- در صورت افشا، فوراً توکن را rotate کنید
- شناسه ادمین را محدود نگه دارید و چک عضویت کانال را دقیق اعمال کنید

## هدف پروژه 🎯
ساخت یک بات جستجوی اپ تلگرام که سریع، کاربردی، قابل نگهداری، و دارای جریان کاربر تمیز و چرخه تحویل کنترل‌شده باشد.



