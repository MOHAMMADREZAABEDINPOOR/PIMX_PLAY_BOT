<div align="center">

<img src="./assets/banner.svg" alt="PIMX_PLAY_BOT 3D Banner" width="100%" />

<a href="https://github.com/MOHAMMADREZAABEDINPOOR/PIMX_PLAY_BOT">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=20&duration=2800&pause=1000&color=00D2FF&center=true&vCenter=true&width=780&lines=Project+Status%3A+Inactive+%2F+Archived+APK+Engine;Production+Telegram+App+Store+%26+Android+APK+Distribution+Engine;Curated+Software+Categories%3A+VPNs%2C+Network+Tools%2C+Media+%26+Security;Instant+Direct+Telegram+File+Delivery+with+Automatic+Cache+Cleanup;Over+3%2C000%2B+Lines+of+Robust+Asynchronous+Python+Architecture;User+Analytics%2C+Broadcast+Engine+%26+Administrative+Control+Panel;Bilingual+Persian+%26+English+Interface+with+Inline+Search+Pagination" alt="Typing SVG" />
</a>

<br/>

[![Project Status: Inactive / Archived](https://img.shields.io/badge/Status-Inactive%20%7C%20Archived-critical?style=for-the-badge&logo=archive)](https://github.com/MOHAMMADREZAABEDINPOOR)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg?style=for-the-badge&logo=gnu)](https://www.gnu.org/licenses/agpl-3.0)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Telegram Bot API](https://img.shields.io/badge/Telegram_Bot_API-v20+-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![Read in Persian](https://img.shields.io/badge/مطالعه_به_فارسی-Persian_README-008080?style=for-the-badge)](#persian-documentation)

<p align="center">
  <b>PIMX_PLAY_BOT</b> is an enterprise Telegram software repository and Android APK application store bot containing over 3,000 lines of robust asynchronous Python. Featuring category-based software browsing (VPN tools, network scanners, media players, utilities), direct high-speed Telegram file delivery, and automated 60-second disk cache pruning, PIMX_PLAY_BOT delivers essential software directly to users without app store restrictions.
</p>

[Project Overview](#-project-overview) •
[Directory Anatomy](#-exhaustive-directory--file-anatomy) •
[Quick Start](#-quick-start) •
[توضیحات فارسی](#persian-documentation) •
[License](#-copyleft-license--legal-attribution)

</div>

---

> [!CAUTION]
> ### 🛑 Project Status: Inactive / Archived (پروژه غیرفعال و بایگانی‌شده)
> **Notice**: This repository is currently **inactive** and maintained solely as an archived open-source APK distribution reference. The live Telegram bot is offline.
>
> **توجه مهم**: این ریپازیتوری در حال حاضر **کاملاً غیرفعال (Inactive / Archived)** می‌باشد و ربات آنلاین فعالی ندارد؛ کدهای آن به عنوان یک آرشیو کامل فنی نگهداری می‌شوند.

## ⚡ Project Overview

In environments where international app stores (Google Play, App Store) are blocked, sanctioned, or filtered, users cannot easily download critical privacy tools, proxies, or communication software.

**PIMX_PLAY_BOT** acts as a decentralized Telegram application repository:
- 📦 **Instant APK Delivery**: Sends intact Android application packages (`.apk`) directly inside the chat.
- 📁 **Structured Software Taxonomy**: Categorized into VPNs, Network Analyzers, Security Tools, and Media Utilities.
- ⏱️ **Auto-Deletion Engine**: Downloaded APK buffers are automatically erased from host disk after 60 seconds to ensure the host machine never exhausts disk space.

---

## 📂 Exhaustive Directory & File Anatomy

```
d:/code/PIMX_PLAY_BOT/
│
├── main.py                          # 3050+ lines of robust bot handlers, search logic & delivery queues
├── users_db.json                    # User account database, permissions, and broadcast recipients
├── bot.log                          # Comprehensive operational runtime log file
└── README.md                        # Master comprehensive bilingual documentation
```

---

## 🚀 Quick Start

```bash
git clone https://github.com/MOHAMMADREZAABEDINPOOR/PIMX_PLAY_BOT.git
cd PIMX_PLAY_BOT

python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux:
source venv/bin/activate

pip install python-telegram-bot httpx aiohttp
python main.py
```

---

## Persian Documentation
### 🇮🇷 مستندات فوق‌العاده مفصل، جامع و فنی به زبان فارسی

### ۱. معرفی ربات فروشگاه نرم‌افزار PIMX_PLAY_BOT
پروژه **PIMX_PLAY_BOT** یک اپ‌استور اختصاصی و فروشگاه نرم‌افزار در بستر تلگرام با بیش از ۳,۰۵۰ سطر کد پایتون است. در زمان‌هایی که دسترسی به گوگل پلی یا بازارهای برنامه‌نویسی به دلیل تحریم یا فیلترینگ مسدود می‌شود، این ربات به عنوان یک مخزن امن و مستقیم، فایل‌های نصبی معتبر اندروید (APK) فیلترشکن‌ها، ابزارهای شبکه و برنامه‌های کاربردی را مستقیماً برای کاربر ارسال می‌کند.

---

### ۲. تشریح فایل‌ها و ویژگی‌های کلیدی
- **`main.py`**: هسته نرم‌افزار شامل موتور جستجوی هوشمند فازی (Fuzzy Search)، دسته‌بندی برنامه‌ها، ارسال پیام همگانی توسط مدیر و حذف خودکار فایل‌ها پس از ۶۰ ثانیه جهت جلوگیری از پر شدن حافظه سرور.
- **`users_db.json`**: دیتابیس کاربران فعال جهت ارائه آمار دقیق و پشتیبانی از اعضای کانال PIMX_PASS.

---

## 📜 Copyleft License & Legal Attribution

Distributed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

---

<div align="center">
<img src="./assets/footer.svg" alt="PIMX_PLAY_BOT 3D Footer" width="100%" />
<sub>Architected by <a href="https://github.com/MOHAMMADREZAABEDINPOOR"><b>MOHAMMADREZA ABEDINPOOR</b></a>. If PIMX_PLAY_BOT helps you distribute software, leave a ⭐!</sub>
</div>
