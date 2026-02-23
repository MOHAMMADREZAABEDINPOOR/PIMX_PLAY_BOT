import logging
import asyncio
import aiohttp
import difflib
import tempfile
import json
import os
import math
import random
import re
import html as html_lib
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote, urljoin, urlparse
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode, ChatAction
from telegram.request import HTTPXRequest

# ==================== تنظیمات اصلی ====================
TOKEN = "8521135628:AAFTqwZlLyT-eCfe5OLDowZFWcNxM5Mit4c"
ADMIN_CHAT_ID = 5675632554
BOT_BRAND = "PIMXPASS"
USERS_DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users_db.json")
DELETE_AFTER_SEND_SECONDS = 60

ADMIN_KB_STATS = "آمار کاربران 📊"
ADMIN_KB_USERS = "لیست کاربران 📋"

KB_SEARCH = "🔍 جستجوی برنامه"
KB_CATEGORIES = "📁 مشاهده دسته‌بندی‌ها"
KB_HELP = "❓ راهنمای استفاده"

CHANNEL_URL = "https://t.me/PIMX_PASS"
CHANNEL_USERNAME = "@PIMX_PASS"
CB_CHECK_JOIN = "check_join"


def _schedule_delete_file(path: Optional[str], delay_s: int = DELETE_AFTER_SEND_SECONDS) -> None:
    path = (path or "").strip()
    if not path:
        return

    async def _job() -> None:
        try:
            await asyncio.sleep(max(0, int(delay_s)))
            if os.path.exists(path):
                os.unlink(path)
        except Exception:
            return

    try:
        asyncio.create_task(_job())
    except Exception:
        # Fallback: best-effort timer on any thread
        import threading

        def _run() -> None:
            try:
                time.sleep(max(0, int(delay_s)))
                if os.path.exists(path):
                    os.unlink(path)
            except Exception:
                return

        threading.Thread(target=_run, daemon=True).start()

# تنظیمات پروکسی - اگر نیازی نیست False کنید
USE_PROXY = False  # ابتدا بدون پروکسی امتحان کنید

# پروکسی‌های ممکن (اگر USE_PROXY = True)
PROXIES = [
    "http://138.68.60.8:3128",  # پروکسی رایگان
    "http://51.158.68.68:8811",  # پروکسی رایگان دیگر
    "http://167.99.236.14:80",   # پروکسی رایگان
]

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== تنظیمات جستجوی چندسایته ====================
RESULTS_PER_PAGE = 10
SEARCH_CACHE_TTL = 15 * 60  # ثانیه
MAX_RESULTS_TOTAL = 500
PROVIDER_LIMIT = 300
APKMIRROR_MAX_PAGES = 5
IZZY_MAX_PAGES = 5
TELEGRAM_UPLOAD_LIMIT_BYTES = 49 * 1024 * 1024  # حدود 49MB
INITIAL_VISIBLE_RESULTS = 100
LOAD_MORE_STEP = 50
SEARCH_CONCURRENCY = 25
DOWNLOAD_CONCURRENCY = 8
QUERY_RESULT_CACHE_TTL = 10 * 60
QUERY_RESULT_CACHE_MAX = 250
QUERY_RESULT_CACHE_VERSION = 4
VERSION_LIST_MAX_LINES = 50

SOURCE_ICONS = {
    "local": "📦",
    "aptoide": "🟦",
    "fdroid": "🟩",
    "openapk": "🟪",
    "apkmirror": "🟧",
    "izzy": "🟨",
}

SOURCE_ORDER = {
    "local": 0,
    "aptoide": 1,
    "apkmirror": 2,
    "openapk": 3,
    "fdroid": 4,
    "izzy": 5,
}

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
TELEGRAM_READ_TIMEOUT = 900
TELEGRAM_WRITE_TIMEOUT = 900


@dataclass
class AppResult:
    title: str
    source: str
    summary: str = ""
    page_url: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchCacheEntry:
    user_id: int
    query: str
    created_at: float
    results: List[AppResult]
    visible_count: Optional[int] = None


SEARCH_CACHE: Dict[str, SearchCacheEntry] = {}
QUERY_RESULT_CACHE: Dict[str, Tuple[float, List[AppResult]]] = {}
SIZE_CACHE: Dict[str, Tuple[int, float]] = {}
SIZE_CACHE_TTL = 24 * 60 * 60  # Ø«Ø§Ù†ÛŒÙ‡
SIZE_CACHE_MAX = 3000
SIZE_PREFETCH_CONCURRENCY = 4
_CONFLICT_STOP_REQUESTED = False
_USERS_LOCK = asyncio.Lock()
_QUERY_CACHE_LOCK = asyncio.Lock()
_SEARCH_SEM = asyncio.Semaphore(SEARCH_CONCURRENCY)
_DOWNLOAD_SEM = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)


def _is_admin_user(user_id: Optional[int]) -> bool:
    try:
        return int(user_id or 0) == int(ADMIN_CHAT_ID)
    except Exception:
        return False


async def _set_admin_reply_keyboard(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """
    Shows admin reply-keyboard buttons under the textbox.
    Telegram needs sending a message to update ReplyKeyboardMarkup; we send an "invisible" placeholder
    so it won't clutter the chat.
    """
    admin_kb = _build_admin_reply_keyboard()

    # Some Telegram clients/API versions treat certain zero-width chars as "empty" and reject the message.
    # Use a mostly-invisible placeholder and fall back to "." if needed.
    for placeholder in ("\u200e", "\u2063", "."):
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=placeholder,
                reply_markup=admin_kb,
                disable_notification=True,
            )
            return
        except Exception:
            continue


def _build_admin_reply_keyboard() -> ReplyKeyboardMarkup:
    # Put admin-only controls first, then main actions.
    keyboard = [
        [ADMIN_KB_STATS, ADMIN_KB_USERS],
        [KB_SEARCH, KB_CATEGORIES],
        [KB_HELP],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)


def _build_user_inline_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(KB_SEARCH, callback_data="search")],
        [InlineKeyboardButton(KB_CATEGORIES, callback_data="show_cats")],
        [InlineKeyboardButton(KB_HELP, callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def _send_categories_message(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard: List[List[InlineKeyboardButton]] = []
    for category, label in CATEGORY_CATALOG:
        keyboard.append([InlineKeyboardButton(f"{label}", callback_data=f"cat_{category}")])
    keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")])
    await context.bot.send_message(
        chat_id=chat_id,
        text="📚 **دسته‌بندی‌ها**\n\nروی هر دسته بزن تا لیست برنامه‌ها رو ببینی 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
    )


async def _is_channel_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, Optional[str]]:
    """
    Returns True if the user is a member/admin/creator of CHANNEL_USERNAME.
    Notes:
    - Telegram requires the bot to be able to access channel members (usually by adding bot to channel as admin).
    - If we can't verify due to Telegram errors, we block access (fail-closed).
    """
    try:
        m = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=int(user_id))
    except Exception as e:
        logger.warning(f"Channel membership check failed for user_id={user_id}: {e}")
        return False, str(e)

    status = str(getattr(m, "status", "") or "").lower()
    if status in {"creator", "administrator", "member"}:
        return True, None
    if status == "restricted":
        return bool(getattr(m, "is_member", False)), None
    return False, None


async def _ensure_channel_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    prompt_in_chat: bool = True,
) -> bool:
    user = update.effective_user
    if not user:
        return True
    # Admin bypass (in private chats, chat_id is user_id)
    if int(getattr(user, "id", 0) or 0) == int(ADMIN_CHAT_ID):
        return True

    ok, error_note = await _is_channel_member(user.id, context)
    if ok:
        return True

    if not prompt_in_chat:
        return False

    text = (
        "🔒 برای استفاده از ربات باید عضو کانال ما باشید.\n\n"
        f"1) اول عضو شو: {CHANNEL_URL}\n"
        "2) بعد روی «✅ بررسی عضویت» بزن."
    )
    if error_note:
        text += (
            "\n\n"
            "⚠️ اگر عضو هستی ولی تایید نمی‌شه، ربات باید داخل کانال ادمین باشه تا بتونه عضویت رو چک کنه.\n"
            f"(خطا: {error_note})"
        )
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 عضویت در کانال", url=CHANNEL_URL)],
            [InlineKeyboardButton("✅ بررسی عضویت", callback_data=CB_CHECK_JOIN)],
        ]
    )

    try:
        if update.callback_query and update.callback_query.message:
            await update.callback_query.message.reply_text(text, reply_markup=kb, disable_web_page_preview=True)
        elif update.message:
            await update.message.reply_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception:
        pass

    return False

def _to_persian_digits(text: str) -> str:
    trans = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    return (text or "").translate(trans)


def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    # Lightweight conversion (ported from common Jalaali algorithms).
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621

    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )

    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461

    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jm = 1 + days // 31
        jd = 1 + (days % 31)
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + ((days - 186) % 30)

    return jy, jm, jd


def _format_jalali_datetime(ts: float) -> str:
    dt = datetime.fromtimestamp(float(ts))
    jy, jm, jd = _gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{dt:%H:%M} {jy:04d}-{jm:02d}-{jd:02d}"


def _clone_results(results: List[AppResult]) -> List[AppResult]:
    cloned: List[AppResult] = []
    for r in results or []:
        cloned.append(
            AppResult(
                title=r.title,
                source=r.source,
                summary=r.summary,
                page_url=r.page_url,
                meta=dict(r.meta or {}),
            )
        )
    return cloned


def _normalize_query_cache_key(query: str) -> str:
    base = " ".join((query or "").strip().lower().split())
    return f"v{QUERY_RESULT_CACHE_VERSION}:{base}"


def _dedupe_results(results: List[AppResult]) -> List[AppResult]:
    """
    De-duplicate results across providers by package or normalized title.
    This prevents repeated identical entries with different URLs.
    """
    seen: set = set()
    deduped: List[AppResult] = []

    for item in results:
        package_key = _normalize_match_text(str(item.meta.get("package") or ""))
        title_key = _normalize_match_text(item.title or "")
        raw_key = (
            item.meta.get("download_url")
            or item.meta.get("release_url")
            or item.meta.get("app_url")
            or item.page_url
            or item.title
        )
        raw_key_norm = str(raw_key).strip().lower()

        # Prefer title-based dedupe to collapse identical app names across sources.
        base_key = title_key or package_key or raw_key_norm
        if title_key and len(title_key) < 4:
            base_key = package_key or raw_key_norm
        if not base_key:
            continue

        if base_key in seen:
            continue
        seen.add(base_key)
        deduped.append(item)

    return deduped


async def _query_cache_get(query: str) -> Optional[List[AppResult]]:
    key = _normalize_query_cache_key(query)
    if not key:
        return None

    async with _QUERY_CACHE_LOCK:
        item = QUERY_RESULT_CACHE.get(key)
        if not item:
            return None
        ts, results = item
        if time.time() - float(ts) > float(QUERY_RESULT_CACHE_TTL):
            QUERY_RESULT_CACHE.pop(key, None)
            return None
        return _clone_results(results)


async def _query_cache_put(query: str, results: List[AppResult]) -> None:
    key = _normalize_query_cache_key(query)
    if not key:
        return

    async with _QUERY_CACHE_LOCK:
        QUERY_RESULT_CACHE[key] = (time.time(), _clone_results(results))
        if len(QUERY_RESULT_CACHE) > int(QUERY_RESULT_CACHE_MAX):
            # Drop oldest entries.
            items = sorted(QUERY_RESULT_CACHE.items(), key=lambda kv: kv[1][0])
            for k, _ in items[: max(0, len(items) - int(QUERY_RESULT_CACHE_MAX))]:
                QUERY_RESULT_CACHE.pop(k, None)


def _load_users_db() -> Dict[str, Any]:
    try:
        if not os.path.exists(USERS_DB_FILE):
            return {"users": {}}
        with open(USERS_DB_FILE, "r", encoding="utf-8") as f:
            data = f.read().strip()
        if not data:
            return {"users": {}}
        obj = json.loads(data)
        if not isinstance(obj, dict):
            return {"users": {}}
        if "users" not in obj or not isinstance(obj.get("users"), dict):
            obj["users"] = {}
        return obj
    except Exception:
        return {"users": {}}


def _save_users_db(db: Dict[str, Any]) -> None:
    try:
        tmp = USERS_DB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        os.replace(tmp, USERS_DB_FILE)
    except Exception:
        return


async def _track_user(update: Update, *, increment: int = 0) -> None:
    try:
        user = update.effective_user
        chat = update.effective_chat
        if not user:
            return
        now = time.time()
        uid = str(user.id)
        async with _USERS_LOCK:
            db = _load_users_db()
            users = db.setdefault("users", {})
            entry = users.get(uid) or {}
            entry.setdefault("user_id", int(user.id))
            entry["username"] = user.username or ""
            entry["first_name"] = user.first_name or ""
            entry["last_name"] = user.last_name or ""
            entry.setdefault("first_seen", now)
            entry["last_seen"] = now
            entry.setdefault("messages", 0)
            if increment:
                entry["messages"] = int(entry.get("messages") or 0) + int(increment)
            entry["chat_id"] = int(chat.id) if chat else entry.get("chat_id")
            users[uid] = entry
            _save_users_db(db)
    except Exception:
        return


def _build_user_stats_text(db: Dict[str, Any]) -> str:
    users = (db or {}).get("users") or {}
    now = datetime.now()
    now_ts = time.time()

    def last_seen_ts(u: Dict[str, Any]) -> float:
        try:
            return float(u.get("last_seen") or 0.0)
        except Exception:
            return 0.0

    total = len(users)
    today_count = 0
    h1 = 0
    h3 = 0
    h24 = 0
    m1 = 0
    m3 = 0
    y3 = 0

    for u in users.values():
        ts = last_seen_ts(u)
        if not ts:
            continue
        dt = datetime.fromtimestamp(ts)
        if dt.date() == now.date():
            today_count += 1
        delta = now_ts - ts
        if delta <= 3600:
            h1 += 1
        if delta <= 3 * 3600:
            h3 += 1
        if delta <= 24 * 3600:
            h24 += 1
        if delta <= 30 * 24 * 3600:
            m1 += 1
        if delta <= 90 * 24 * 3600:
            m3 += 1
        if delta <= 3 * 365 * 24 * 3600:
            y3 += 1

    return (
        "📊 آمار کاربران\n"
        "────────────────\n"
        f"👥 کل کاربران: {int(total)}\n"
        "────────────────\n"
        f"🗓️ امروز: {int(today_count)}\n"
        f"⏱️ ۱ ساعت اخیر: {int(h1)}\n"
        f"⏱️ ۳ ساعت اخیر: {int(h3)}\n"
        f"🕘 ۲۴ ساعت اخیر: {int(h24)}\n"
        f"🗓️ ۱ ماه اخیر: {int(m1)}\n"
        f"🗓️ ۳ ماه اخیر: {int(m3)}\n"
        f"🗓️ ۳ سال اخیر: {int(y3)}\n"
    )


def _format_users_list_text(db: Dict[str, Any]) -> List[str]:
    users = (db or {}).get("users") or {}
    items = list(users.values())
    items.sort(key=lambda u: float(u.get("last_seen") or 0.0), reverse=True)

    now = datetime.now()
    hour12 = now.hour % 12 or 12
    ampm = "AM" if now.hour < 12 else "PM"
    header = f"{BOT_BRAND}, [{now.month}/{now.day}/{now.year} {hour12}:{now.minute:02d} {ampm}]"

    lines: List[str] = [header]
    for u in items:
        first = str(u.get("first_name") or "").strip()
        last = str(u.get("last_name") or "").strip()
        name = (first + " " + last).strip() or "کاربر"
        username = str(u.get("username") or "").strip()
        username_disp = f"@{username}" if username else "@-"
        msgs = int(u.get("messages") or 0)
        ts = float(u.get("last_seen") or 0.0)
        when = _format_jalali_datetime(ts) if ts else "-"
        lines.append(f"👤 {name} | 🆔 {username_disp} | 🔁 {msgs} | 🕒 {when}")

    # Chunk to Telegram max message length
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for line in lines:
        add_len = len(line) + 1
        if cur and cur_len + add_len > 3500:
            chunks.append("\n".join(cur))
            cur = [header]
            cur_len = len(header) + 1
        cur.append(line)
        cur_len += add_len
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def _cleanup_search_cache() -> None:
    now = time.time()
    expired_tokens = [t for t, v in SEARCH_CACHE.items() if now - v.created_at > SEARCH_CACHE_TTL]
    for t in expired_tokens:
        SEARCH_CACHE.pop(t, None)


def _cleanup_size_cache() -> None:
    now = time.time()
    expired_urls = [u for u, (_, ts) in SIZE_CACHE.items() if now - ts > SIZE_CACHE_TTL]
    for u in expired_urls:
        SIZE_CACHE.pop(u, None)

    if len(SIZE_CACHE) <= SIZE_CACHE_MAX:
        return

    # drop oldest
    by_age = sorted(SIZE_CACHE.items(), key=lambda kv: kv[1][1])
    for url, _ in by_age[: max(0, len(SIZE_CACHE) - SIZE_CACHE_MAX)]:
        SIZE_CACHE.pop(url, None)


def _size_cache_get(url: str) -> Optional[int]:
    url = (url or "").strip()
    if not url:
        return None
    item = SIZE_CACHE.get(url)
    if not item:
        return None
    size, ts = item
    if time.time() - ts > SIZE_CACHE_TTL:
        SIZE_CACHE.pop(url, None)
        return None
    return int(size) if isinstance(size, int) and size > 0 else None


def _size_cache_set(url: str, size_bytes: int) -> None:
    url = (url or "").strip()
    if not url:
        return
    if not isinstance(size_bytes, int) or size_bytes <= 0:
        return
    SIZE_CACHE[url] = (int(size_bytes), time.time())


def _new_token() -> str:
    for _ in range(5):
        token = secrets.token_hex(4)
        if token not in SEARCH_CACHE:
            return token
    return secrets.token_hex(6)


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 1)].rstrip() + "…"


def _format_size(size_bytes: Optional[int]) -> str:
    if not size_bytes or size_bytes <= 0:
        return ""
    if size_bytes < 1024 * 1024:
        return f"{size_bytes/1024:.0f}KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes/(1024*1024):.1f}MB"
    return f"{size_bytes/(1024*1024*1024):.2f}GB"


def _result_size_text(result: "AppResult") -> str:
    size_bytes = result.meta.get("size_bytes")
    if isinstance(size_bytes, int) and int(size_bytes) > 0:
        return _format_size(int(size_bytes))

    size_label = str(result.meta.get("size_label") or "").strip()
    if size_label:
        return re.sub(r"\\s+", "", size_label)

    return ""


def _extract_version_label(result: "AppResult") -> str:
    meta_version = str(result.meta.get("version") or "").strip()
    if meta_version:
        return meta_version
    title = str(result.title or "")
    m = re.search(r"\b(v|ver|version)\s*([0-9]+(\.[0-9]+){1,3})\b", title, flags=re.I)
    if m:
        return f"v{m.group(2)}"
    m2 = re.search(r"\b([0-9]+(\.[0-9]+){1,3})\b", title)
    if m2:
        return m2.group(1)
    return "-"


def _version_tuple(result: "AppResult") -> Tuple[int, ...]:
    label = _extract_version_label(result)
    nums = [int(x) for x in re.findall(r"\d+", label)]
    if not nums:
        return tuple()
    return tuple(nums[:6])


def _app_identity_key(result: "AppResult") -> str:
    pkg = _normalize_match_text(str(result.meta.get("package") or ""))
    if pkg:
        return f"pkg:{pkg}"
    title = str(result.title or "")
    simplified = re.sub(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}", " ", title)
    simplified = re.sub(r"\b(v|ver|version)\s*\d+(\.\d+){0,4}\b", " ", simplified, flags=re.I)
    simplified = re.sub(r"\b\d+(\.\d+){1,4}\b", " ", simplified)
    simplified = re.sub(r"\s+", " ", simplified).strip()
    key = _normalize_match_text(simplified)
    if key:
        return key
    return _normalize_match_text(title) or title


def _tie_break_key(result: "AppResult") -> Tuple[int, int, int, int]:
    return (
        1 if result.meta.get("kind") == "direct" else 0,
        1 if _result_size_text(result) else 0,
        -SOURCE_ORDER.get(result.source, 99),
        len(str(result.title or "")),
    )


def _is_newer_result(candidate: "AppResult", current: "AppResult") -> bool:
    v_cand = _version_tuple(candidate)
    v_curr = _version_tuple(current)
    if v_cand and v_curr:
        if v_cand != v_curr:
            return v_cand > v_curr
    elif v_cand and not v_curr:
        return True
    elif v_curr and not v_cand:
        return False
    return _tie_break_key(candidate) > _tie_break_key(current)


def _pick_latest_per_app(results: List[AppResult]) -> List[AppResult]:
    latest: Dict[str, AppResult] = {}
    for item in results:
        key = _app_identity_key(item)
        if not key:
            continue
        prev = latest.get(key)
        if not prev or _is_newer_result(item, prev):
            latest[key] = item
    return list(latest.values())


def _build_results_message_text(
    *,
    query: str,
    results: List[AppResult],
    page: int,
    visible_total: int,
) -> str:
    total = len(results)
    shown = min(total, int(visible_total))
    more_hint = "\n\n➕ برای دیدن نتایج بیشتر، روی «۵۰ تای دیگه» بزن." if total > shown else ""

    page = max(0, int(page))
    start = page * int(RESULTS_PER_PAGE)
    if shown <= 0:
        start = 0
    elif start >= shown:
        start = max(0, shown - int(RESULTS_PER_PAGE))
    end = min(shown, start + int(RESULTS_PER_PAGE), start + int(VERSION_LIST_MAX_LINES))

    lines: List[str] = []
    for idx in range(start, end):
        r = results[idx]
        version = _extract_version_label(r)
        size_text = _result_size_text(r) or "-"
        lines.append(f"{idx+1}. نسخه: {version} | حجم: {size_text}")

    versions_block = "\n".join(lines) if lines else "—"

    return (
        f"✅ **{len(results)} نتیجه برای '{query}' پیدا شد.**\n"
        f"🔎 فعلاً {shown} تا نمایش داده می‌شود.{more_hint}\n\n"
        "👇 برای دانلود روی مورد دلخواه کلیک کنید:\n\n"
        "📄 **نسخه‌ها (همین صفحه):**\n"
        f"{versions_block}"
    )

def _safe_filename(name: str, max_len: int = 120) -> str:
    name = (name or "file").strip()
    name = re.sub(r'[<>:"/\\\\|?*\\n\\r\\t]+', "_", name)
    name = re.sub(r"\\s+", " ", name).strip()
    if len(name) > max_len:
        root, ext = os.path.splitext(name)
        keep = max_len - len(ext)
        name = root[:keep].rstrip() + ext
    return name or "file"


def _normalize_match_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[_\\-]+", " ", text)
    text = re.sub(r"[^0-9a-z\u0600-\u06FF ]+", " ", text)
    text = re.sub(r"\\s+", " ", text).strip()
    return text


def _relevance_score(query: str, result: "AppResult") -> float:
    q = _normalize_match_text(query)
    if not q:
        return 0.0

    title = _normalize_match_text(result.title)
    package = _normalize_match_text(str(result.meta.get("package") or ""))

    haystacks = [title]
    if package:
        haystacks.append(package)

    score = 0.0

    # Exact / substring matches
    if q in haystacks:
        score += 1000.0
    else:
        for h in haystacks:
            if q == h:
                score += 950.0
            elif q and h.startswith(q):
                score += 800.0
            elif q and q in h:
                score += 650.0

    # Token coverage
    tokens = [t for t in q.split(" ") if len(t) >= 2]
    if tokens:
        matched = 0
        for t in tokens:
            if any(t in h for h in haystacks):
                matched += 1
        score += 40.0 * matched
        if matched == len(tokens):
            score += 120.0

    # Fuzzy similarity (helps short queries)
    try:
        score += 120.0 * difflib.SequenceMatcher(a=q, b=title).ratio()
    except Exception:
        pass

    # Source preference + direct links
    score += max(0, 20 - SOURCE_ORDER.get(result.source, 20))
    if result.meta.get("kind") == "direct":
        score += 15.0

    # Prefer known sizes
    if isinstance(result.meta.get("size_bytes"), int) and int(result.meta["size_bytes"]) > 0:
        score += 5.0
    if result.meta.get("size_label"):
        score += 3.0

    return score


def _is_direct_download_url(url: str) -> bool:
    url = (url or "").strip()
    if not url:
        return False

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()

    if path.endswith((".apk", ".apkm", ".xapk", ".apks")):
        return True

    if host.endswith("telegram.org") and path.endswith("/dl/android/apk"):
        return True

    return False


def _pick_proxy() -> Optional[str]:
    if not USE_PROXY or not PROXIES:
        return None
    return random.choice(PROXIES)


async def _fetch_text(session: aiohttp.ClientSession, url: str, *, timeout_s: int = 25) -> str:
    proxy = _pick_proxy()
    headers = {"User-Agent": DEFAULT_UA}
    async with session.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=timeout_s), headers=headers) as resp:
        resp.raise_for_status()
        return await resp.text(errors="ignore")


async def _fetch_json(session: aiohttp.ClientSession, url: str, *, timeout_s: int = 25) -> Any:
    proxy = _pick_proxy()
    headers = {"User-Agent": DEFAULT_UA, "Accept": "application/json"}
    async with session.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=timeout_s), headers=headers) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)


async def _download_to_tempfile(
    session: aiohttp.ClientSession,
    url: str,
    *,
    timeout_s: int = 180,
    max_bytes: Optional[int] = None,
    progress_cb: Optional[Callable[[int, Optional[int]], Awaitable[None]]] = None,
) -> Tuple[Optional[str], int, str, str]:
    """
    دانلود فایل به صورت استریم داخل فایل موقت.
    خروجی: (path, size_bytes, final_url, content_type)
    """
    proxy = _pick_proxy()
    headers = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}

    timeout = aiohttp.ClientTimeout(total=timeout_s, connect=30, sock_read=60)
    async with session.get(
        url,
        proxy=proxy,
        timeout=timeout,
        headers=headers,
        allow_redirects=True,
    ) as resp:
        if resp.status != 200:
            return None, 0, str(resp.url), resp.headers.get("Content-Type", "")

        content_type = resp.headers.get("Content-Type", "")
        content_length = resp.headers.get("Content-Length")
        expected_total: Optional[int] = None
        if content_length and str(content_length).isdigit():
            try:
                expected_total = int(content_length)
            except Exception:
                expected_total = None

        if max_bytes and expected_total and expected_total > max_bytes:
            return None, expected_total, str(resp.url), content_type
        total_size = 0

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tmp", prefix="download_")
        tmp_path = tmp.name
        try:
            if progress_cb:
                try:
                    await progress_cb(0, expected_total)
                except Exception:
                    pass
            async for chunk in resp.content.iter_chunked(64 * 1024):
                if not chunk:
                    continue
                if max_bytes and total_size + len(chunk) > max_bytes:
                    try:
                        tmp.close()
                    except Exception:
                        pass
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass
                    return None, total_size + len(chunk), str(resp.url), content_type
                tmp.write(chunk)
                total_size += len(chunk)
                if progress_cb:
                    try:
                        await progress_cb(total_size, expected_total)
                    except Exception:
                        pass
            tmp.close()
        except Exception:
            try:
                tmp.close()
            except Exception:
                pass
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise

        if progress_cb:
            try:
                await progress_cb(total_size, expected_total)
            except Exception:
                pass

        return tmp_path, total_size, str(resp.url), content_type


async def _guess_content_length(session: aiohttp.ClientSession, url: str, *, timeout_s: int = 20) -> Optional[int]:
    proxy = _pick_proxy()
    timeout = aiohttp.ClientTimeout(total=timeout_s, connect=15, sock_read=15)
    headers = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}

    try:
        async with session.head(url, proxy=proxy, timeout=timeout, headers=headers, allow_redirects=True) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and str(cl).isdigit():
                return int(cl)
    except Exception:
        pass

    # fallback: range request (دریافت Content-Range)
    try:
        range_headers = {**headers, "Range": "bytes=0-0"}
        async with session.get(url, proxy=proxy, timeout=timeout, headers=range_headers, allow_redirects=True) as resp:
            cr = resp.headers.get("Content-Range")  # bytes 0-0/12345
            if cr and "/" in cr:
                total = cr.split("/")[-1].strip()
                if total.isdigit():
                    return int(total)
            cl = resp.headers.get("Content-Length")
            if cl and str(cl).isdigit():
                return int(cl)
    except Exception:
        pass

    return None


async def _prefetch_page_sizes(results: List["AppResult"], page: int) -> None:
    """Best-effort: fill missing sizes for the visible page (direct links only)."""
    try:
        _cleanup_size_cache()
        total = len(results)
        if total <= 0:
            return

        start = max(0, page) * RESULTS_PER_PAGE
        end = min(total, start + RESULTS_PER_PAGE)
        if start >= end:
            return

        candidates: List[Tuple["AppResult", str]] = []
        for r in results[start:end]:
            if _result_size_text(r):
                continue
            if r.meta.get("kind") != "direct":
                continue
            dl = str(r.meta.get("download_url") or "").strip()
            if not dl:
                continue

            cached = _size_cache_get(dl)
            if cached:
                r.meta["size_bytes"] = int(cached)
                continue

            candidates.append((r, dl))

        if not candidates:
            return

        headers = {"User-Agent": DEFAULT_UA, "Accept": "*/*"}
        timeout = aiohttp.ClientTimeout(total=25, connect=10, sock_read=10)
        sem = asyncio.Semaphore(SIZE_PREFETCH_CONCURRENCY)

        async with aiohttp.ClientSession(timeout=timeout, headers=headers, connector=aiohttp.TCPConnector(ssl=False)) as session:
            async def _one(res: "AppResult", url: str) -> None:
                async with sem:
                    try:
                        size = await _guess_content_length(session, url, timeout_s=18)
                        if size and size > 0:
                            res.meta["size_bytes"] = int(size)
                            _size_cache_set(url, int(size))
                    except Exception:
                        return

            await asyncio.gather(*(_one(r, u) for r, u in candidates), return_exceptions=True)
    except Exception:
        return

# ==================== دیتابیس ساده‌شده ====================
APP_DATABASE = {
    "vpn": [
        {
            "name": "✅ Psiphon Pro VPN",
            "url": "https://psiphon.ca/psiphon3.apk",
            "size": "15MB",
            "description": "VPN قدرتمند برای عبور از فیلترینگ",
            "version": "v368",
            "rating": "⭐️⭐️⭐️⭐️⭐️ 4.8/5"
        },
        {
            "name": "🎨 HTTP Custom",
            "url": "https://apkpure.com/http-custom/com.delta.httpcustom/download/350-APK",
            "size": "14MB",
            "description": "قابلیت تنظیمات پیشرفته",
            "version": "v2.3.1",
            "rating": "⭐️⭐️⭐️⭐️ 4.4/5"
        },
        {
            "name": "🛠️ HTTP Injector",
            "url": "https://apkpure.com/http-injector/com.evozi.injector/download",
            "size": "12MB",
            "description": "برای حرفه‌ای‌ها",
            "version": "v4.1.3",
            "rating": "⭐️⭐️⭐️⭐️⭐️ 4.7/5"
        },
        {
            "name": "⚡ Thunder VPN",
            "url": "https://apkpure.com/thunder-vpn/com.thunder.vpn/download",
            "size": "18MB",
            "description": "سبک و سریع",
            "version": "v5.2.1",
            "rating": "⭐️⭐️⭐️⭐️ 4.2/5"
        },
        {
            "name": "🔒 NordVPN",
            "url": "https://downloads.nordcdn.com/apps/android/latest/nordvpn_7.15.0.apk",
            "size": "35MB",
            "description": "امنیت حرفه‌ای",
            "version": "v7.15.0",
            "rating": "⭐️⭐️⭐️⭐️⭐️ 4.8/5"
        }
    ],
    "تلگرام": [
        {
            "name": "📱 Telegram Messenger",
            "url": "https://telegram.org/dl/android/apk",
            "size": "65MB",
            "description": "تلگرام رسمی",
            "version": "v10.5.0",
            "rating": "⭐️⭐️⭐️⭐️⭐️ 4.8/5"
        },
        {
            "name": "⚡ Telegram X",
            "url": "https://telegram.org/dl/android/apk?x=1",
            "size": "70MB",
            "description": "تلگرام سریع‌تر",
            "version": "v10.5.0",
            "rating": "⭐️⭐️⭐️⭐️⭐️ 4.7/5"
        },
        {
            "name": "➕ Telegram Plus",
            "url": "https://apkpure.com/telegram-plus/org.plus.messenger/download",
            "size": "75MB",
            "description": "قابلیت‌های اضافی",
            "version": "v9.8.2",
            "rating": "⭐️⭐️⭐️⭐️⭐️ 4.9/5"
        }
    ],
    "واتساپ": [
        {
            "name": "💚 WhatsApp Messenger",
            "url": "https://www.whatsapp.com/android/apk/WhatsApp.apk",
            "size": "45MB",
            "description": "نسخه رسمی",
            "version": "v2.24.10.72",
            "rating": "⭐️⭐️⭐️⭐️⭐️ 4.8/5"
        },
        {
            "name": "🟢 WhatsApp GB",
            "url": "https://gbapps.net/download-gbwhatsapp/GBWhatsApp_17.50.apk",
            "size": "60MB",
            "description": "محبوب‌ترین ماد",
            "version": "v17.50",
            "rating": "⭐️⭐️⭐️⭐️⭐️ 5.0/5"
        },
        {
            "name": "💼 WhatsApp Business",
            "url": "https://www.whatsapp.com/android/apk/WhatsAppBusiness.apk",
            "size": "50MB",
            "description": "برای کسب‌وکار",
            "version": "v2.24.10.72",
            "rating": "⭐️⭐️⭐️⭐️⭐️ 4.7/5"
        }
    ],
    "اینستاگرام": [
        {
            "name": "📸 Instagram",
            "url": "https://www.instagram.com/android/apk/Instagram.apk",
            "size": "70MB",
            "description": "نسخه رسمی",
            "version": "v319.0.0.0.0",
            "rating": "⭐️⭐️⭐️⭐️⭐️ 4.7/5"
        },
        {
            "name": "➕ Instagram Plus",
            "url": "https://apkcombo.com/instagram-plus/com.plus.instagram/download/apk",
            "size": "85MB",
            "description": "دانلود عکس و ویدیو",
            "version": "v280.0",
            "rating": "⭐️⭐️⭐️⭐️⭐️ 4.9/5"
        },
        {
            "name": "⚡ Instagram Lite",
            "url": "https://www.instagram.com/android/lite/InstagramLite.apk",
            "size": "15MB",
            "description": "سبک و سریع",
            "version": "v347.0.0.0.0",
            "rating": "⭐️⭐️⭐️⭐️ 4.3/5"
        }
    ],
    "🎮 بازی": [],
    "🌐 مرورگر": [],
    "🧰 ابزارها": [],
    "🎵 موسیقی": [],
    "🎬 ویدیو": [],
    "📷 عکاسی": [],
    "🎓 آموزش": [],
    "📚 کتاب": [],
    "🗺️ نقشه": [],
    "🛡️ امنیت": [],
    "💳 مالی": [],
    "🛍️ فروشگاه": [],
    "🩺 سلامت": [],
    "🤖 هوش‌مصنوعی": [],
    "🗓️ ابزار روزمره": []
}

# ترتیب نمایش دسته‌بندی‌ها (حداقل ۱۵ دسته)
CATEGORY_CATALOG: List[Tuple[str, str]] = [
    ("vpn", "🔐 فیلتر شکن"),
    ("تلگرام", "✈️ تلگرام"),
    ("واتساپ", "💚 واتساپ"),
    ("اینستاگرام", "📸 اینستاگرام"),
    ("🎮 بازی", "🎮 بازی"),
    ("🌐 مرورگر", "🌐 مرورگر"),
    ("🧰 ابزارها", "🧰 ابزارها"),
    ("🎵 موسیقی", "🎵 موسیقی"),
    ("🎬 ویدیو", "🎬 ویدیو"),
    ("📷 عکاسی", "📷 عکاسی"),
    ("🎓 آموزش", "🎓 آموزش"),
    ("📚 کتاب", "📚 کتاب"),
    ("🗺️ نقشه", "🗺️ نقشه"),
    ("🛡️ امنیت", "🛡️ امنیت"),
    ("💳 مالی", "💳 مالی"),
    ("🛍️ فروشگاه", "🛍️ فروشگاه"),
    ("🩺 سلامت", "🩺 سلامت"),
    ("🤖 هوش‌مصنوعی", "🤖 هوش‌مصنوعی"),
    ("🗓️ ابزار روزمره", "🗓️ ابزار روزمره"),
]

# Prefer "safe" internal keys for callback_data, but keep legacy keys for compatibility.
_LEGACY_CATEGORY_KEYS: Dict[str, str] = {
    "games": "\U0001f3ae بازی",
    "browsers": "\U0001f310 مرورگر",
    "tools": "\U0001f9f0 ابزارها",
    "music": "\U0001f3b5 موسیقی",
    "video": "\U0001f3ac ویدیو",
    "photo": "\U0001f4f7 عکاسی",
    "education": "\U0001f393 آموزش",
    "books": "\U0001f4da کتاب",
    "maps": "\U0001f5fa\ufe0f نقشه",
    "security": "\U0001f6e1\ufe0f امنیت",
    "finance": "\U0001f4b3 مالی",
    "shopping": "\U0001f6cd\ufe0f فروشگاه",
    "health": "\U0001fa7a سلامت",
    "ai": "\U0001f916 هوش\u200cمصنوعی",
    "daily": "\U0001f5d3\ufe0f ابزار روزمره",
}

for _safe_key, _legacy_key in _LEGACY_CATEGORY_KEYS.items():
    if _safe_key not in APP_DATABASE:
        APP_DATABASE[_safe_key] = APP_DATABASE.get(_legacy_key, [])

# Override catalog with safe keys (15+ categories).
CATEGORY_CATALOG = [
    ("vpn", "🔐 فیلتر شکن"),
    ("تلگرام", "✈️ تلگرام"),
    ("واتساپ", "💚 واتساپ"),
    ("اینستاگرام", "📸 اینستاگرام"),
    ("games", "🎮 بازی"),
    ("browsers", "🌐 مرورگر"),
    ("tools", "🧰 ابزارها"),
    ("music", "🎵 موسیقی"),
    ("video", "🎬 ویدیو"),
    ("photo", "📷 عکاسی"),
    ("education", "🎓 آموزش"),
    ("books", "📚 کتاب"),
    ("maps", "🗺️ نقشه"),
    ("security", "🛡️ امنیت"),
    ("finance", "💳 مالی"),
    ("shopping", "🛍️ فروشگاه"),
    ("health", "🩺 سلامت"),
    ("ai", "🤖 هوش‌مصنوعی"),
    ("daily", "🗓️ ابزار روزمره"),
]

CATEGORY_LABELS: Dict[str, str] = {k: v for k, v in CATEGORY_CATALOG}

CATEGORY_ALIASES: Dict[str, str] = {
    "بازی": "games",
    "game": "games",
    "games": "games",
    "مرورگر": "browsers",
    "browser": "browsers",
    "browsers": "browsers",
    "ابزار": "tools",
    "ابزارها": "tools",
    "tools": "tools",
    "موسیقی": "music",
    "music": "music",
    "ویدیو": "video",
    "video": "video",
    "عکاسی": "photo",
    "photo": "photo",
    "آموزش": "education",
    "education": "education",
    "کتاب": "books",
    "books": "books",
    "نقشه": "maps",
    "map": "maps",
    "maps": "maps",
    "امنیت": "security",
    "security": "security",
    "مالی": "finance",
    "finance": "finance",
    "فروشگاه": "shopping",
    "shopping": "shopping",
    "سلامت": "health",
    "health": "health",
    "هوش مصنوعی": "ai",
    "هوش\u200cمصنوعی": "ai",
    "ai": "ai",
    "ابزار روزمره": "daily",
    "روزمره": "daily",
    "daily": "daily",
}

CATEGORY_SEARCH_QUERIES: Dict[str, str] = {
    "vpn": "vpn",
    "تلگرام": "telegram",
    "واتساپ": "whatsapp",
    "اینستاگرام": "instagram",
    "games": "game",
    "browsers": "browser",
    "tools": "tools",
    "music": "music",
    "video": "video",
    "photo": "photo editor",
    "education": "education",
    "books": "books",
    "maps": "maps",
    "security": "security",
    "finance": "wallet",
    "shopping": "shopping",
    "health": "health",
    "ai": "ai",
    "daily": "calendar",
}

def _category_label(category_key: str) -> str:
    return CATEGORY_LABELS.get(category_key, category_key)

# ==================== تابع جستجوی ساده ====================
def search_apps(query):
    """جستجوی ساده در دیتابیس"""
    query_lower = query.lower().strip()
    query_lower = CATEGORY_ALIASES.get(query_lower, query_lower)
    results = []
    
    # جستجو در دسته‌بندی‌ها
    if query_lower in APP_DATABASE:
        results.extend(APP_DATABASE[query_lower])
    
    # جستجو در نام برنامه‌ها
    for category, apps in APP_DATABASE.items():
        for app in apps:
            if query_lower in app['name'].lower():
                if app not in results:
                    results.append(app)
    
    # اگر چیزی پیدا نشد، برنامه‌های محبوب رو نشون بده
    if not results:
        for cat in ["vpn", "تلگرام", "واتساپ"]:
            if cat in APP_DATABASE:
                results.extend(APP_DATABASE[cat][:2])
    
    return results[:8]  # حداکثر 8 نتیجه

# ==================== جستجو در سایت‌ها ====================
def _local_results_from_apps(apps: List[Dict[str, str]]) -> List[AppResult]:
    results: List[AppResult] = []
    for app in apps:
        url = (app.get("url") or "").strip()
        if not _is_direct_download_url(url):
            continue
        results.append(
            AppResult(
                title=app.get("name", "App"),
                source="local",
                summary=app.get("description", ""),
                page_url=url,
                meta={
                    "kind": "direct",
                    "download_url": url,
                    "size_label": app.get("size", ""),
                    "version": app.get("version", ""),
                    "rating": app.get("rating", ""),
                },
            )
        )
    return results


async def _provider_aptoide(session: aiohttp.ClientSession, query: str, limit: int = 8) -> List[AppResult]:
    try:
        q = quote(query.strip(), safe="")

        page_size = 20
        offset = 0
        results: List[AppResult] = []
        seen: set = set()

        while len(results) < limit:
            url = f"https://ws75.aptoide.com/api/7/apps/search/query={q}/limit={page_size}/offset={offset}"
            try:
                data = await _fetch_json(session, url, timeout_s=20)
            except Exception as e:
                logger.warning(f"Aptoide page fetch failed (offset={offset}): {e}")
                break
            datalist = (data or {}).get("datalist") or {}
            items = datalist.get("list") or []
            if not items:
                break

            for item in items:
                try:
                    name = str(item.get("name") or "").strip()
                    package = str(item.get("package") or "").strip()
                    file_info = item.get("file") or {}
                    vername = str(file_info.get("vername") or "").strip()
                    filesize = file_info.get("filesize")
                    size_bytes = (
                        int(filesize)
                        if isinstance(filesize, (int, float, str)) and str(filesize).isdigit()
                        else None
                    )
                    download_url = str(file_info.get("path") or "").strip()
                    rating_avg = (((item.get("stats") or {}).get("rating") or {}).get("avg")) or None

                    if not name or not download_url:
                        continue

                    key = download_url or package or name
                    if key in seen:
                        continue
                    seen.add(key)

                    results.append(
                        AppResult(
                            title=name,
                            source="aptoide",
                            summary=package or "Aptoide",
                            page_url=download_url,
                            meta={
                                "kind": "direct",
                                "download_url": download_url,
                                "package": package,
                                "version": vername,
                                "size_bytes": size_bytes,
                                "rating": rating_avg,
                            },
                        )
                    )
                    if len(results) >= limit:
                        break
                except Exception:
                    continue

            next_offset = datalist.get("next")
            try:
                next_offset_int = int(next_offset)
            except Exception:
                next_offset_int = offset + page_size

            if next_offset_int <= offset:
                break
            offset = next_offset_int

        return results[:limit]
    except Exception as e:
        logger.warning(f"Aptoide search failed: {e}")
        return []


async def _provider_fdroid(session: aiohttp.ClientSession, query: str, limit: int = 8) -> List[AppResult]:
    try:
        q = quote(query.strip(), safe="")
        url = f"https://search.f-droid.org/?q={q}"
        html = await _fetch_text(session, url, timeout_s=20)

        pattern = re.compile(
            r'<a class="package-header" href="https://f-droid\\.org/en/packages/(?P<pkg>[^"]+)".*?>'
            r".*?<h4 class=\"package-name\">\\s*(?P<name>.*?)\\s*</h4>"
            r".*?<span class=\"package-summary\">(?P<summary>[^<]*)</span>",
            re.S,
        )

        results: List[AppResult] = []
        for m in pattern.finditer(html):
            pkg = html_lib.unescape(m.group("pkg")).strip()
            name = html_lib.unescape(re.sub(r"\s+", " ", m.group("name"))).strip()
            summary = html_lib.unescape(m.group("summary") or "").strip()
            if not pkg or not name:
                continue
            results.append(
                AppResult(
                    title=name,
                    source="fdroid",
                    summary=summary,
                    page_url=f"https://f-droid.org/en/packages/{pkg}",
                    meta={"kind": "fdroid", "package": pkg},
                )
            )
            if len(results) >= limit:
                break

        return results
    except Exception as e:
        logger.warning(f"F-Droid search failed: {e}")
        return []


async def _provider_openapk(session: aiohttp.ClientSession, query: str, limit: int = 8) -> List[AppResult]:
    try:
        q = quote(query.strip(), safe="")
        url = f"https://www.openapk.net/search/?q={q}"
        html = await _fetch_text(session, url, timeout_s=25)

        pattern = re.compile(
            r'<a href="(?P<href>/[^"]+/[^"]+/)"[^>]*class="list-item"[^>]*>'
            r".*?<span class=\"name\">(?P<name>[^<]+)</span>\\s*"
            r"<span class=\"desc\">(?P<desc>[^<]*)</span>",
            re.S,
        )

        results: List[AppResult] = []
        for m in pattern.finditer(html):
            href = m.group("href").strip()
            name = html_lib.unescape(m.group("name")).strip()
            desc = html_lib.unescape(m.group("desc") or "").strip()
            if not href or not name:
                continue
            app_url = urljoin("https://www.openapk.net", href)
            results.append(
                AppResult(
                    title=name,
                    source="openapk",
                    summary=desc,
                    page_url=app_url,
                    meta={"kind": "openapk", "app_url": app_url},
                )
            )
            if len(results) >= limit:
                break

        return results
    except Exception as e:
        logger.warning(f"OpenAPK search failed: {e}")
        return []


async def _provider_apkmirror(session: aiohttp.ClientSession, query: str, limit: int = 8) -> List[AppResult]:
    try:
        q = quote(query.strip(), safe="")
        pattern = re.compile(
            r'<a class="fontBlack" href="(?P<href>/apk/[^"]+/[^"]+/[^"]+-release/)">(?P<title>[^<]+)</a>'
        )

        results: List[AppResult] = []
        seen: set = set()

        for page in range(1, APKMIRROR_MAX_PAGES + 1):
            url = f"https://www.apkmirror.com/?post_type=app_release&searchtype=apk&s={q}"
            if page > 1:
                url += f"&page={page}"

            try:
                html = await _fetch_text(session, url, timeout_s=30)
            except Exception as e:
                logger.warning(f"APKMirror page fetch failed (page={page}): {e}")
                break
            before = len(results)

            for m in pattern.finditer(html):
                href = m.group("href").strip()
                title = html_lib.unescape(m.group("title")).strip()
                if not href or not title:
                    continue
                release_url = urljoin("https://www.apkmirror.com", href)
                if release_url in seen:
                    continue
                seen.add(release_url)
                results.append(
                    AppResult(
                        title=title,
                        source="apkmirror",
                        summary="APKMirror release",
                        page_url=release_url,
                        meta={"kind": "apkmirror", "release_url": release_url},
                    )
                )
                if len(results) >= limit:
                    return results[:limit]

            if len(results) == before:
                break

        return results[:limit]
    except Exception as e:
        logger.warning(f"APKMirror search failed: {e}")
        return []


async def _provider_izzy(session: aiohttp.ClientSession, query: str, limit: int = 8) -> List[AppResult]:
    """جستجو در IzzyOnDroid Repo (apt.izzysoft.de)"""
    try:
        q = quote(query.strip(), safe="")
        # عنوان + توضیح + لینک دانلود
        pattern = re.compile(
            r"<div class='approw'>.*?<span class='boldname'>(?P<name>[^<]+)</span>.*?"
            r"<div class='appdetailrow'>\\s*<div class='appdetailcell'>(?P<desc>[^<]*)</div>\\s*</div>.*?"
            r"<a class='paddedlink' href='(?P<dl>[^']+\\.apk)'>Download</a>",
            re.S,
        )

        results: List[AppResult] = []
        seen: set = set()

        page_size = min(100, max(10, limit))
        for page in range(1, IZZY_MAX_PAGES + 1):
            url = (
                f"https://apt.izzysoft.de/fdroid/index.php/list/page/{page}"
                f"?repo=iod;doFilter=1;searchterm={q};limit={page_size}"
            )
            html = await _fetch_text(session, url, timeout_s=30)
            before = len(results)

            for m in pattern.finditer(html):
                name = html_lib.unescape(m.group("name")).strip()
                desc = html_lib.unescape(m.group("desc") or "").strip()
                dl = m.group("dl").strip()
                if not name or not dl:
                    continue
                dl_url = urljoin("https://apt.izzysoft.de/fdroid/", dl)
                if dl_url in seen:
                    continue
                seen.add(dl_url)
                results.append(
                    AppResult(
                        title=name,
                        source="izzy",
                        summary=desc,
                        page_url=dl_url,
                        meta={"kind": "direct", "download_url": dl_url},
                    )
                )
                if len(results) >= limit:
                    return results[:limit]

            if len(results) == before:
                break

        return results[:limit]
    except Exception as e:
        logger.warning(f"Izzy search failed: {e}")
        return []


async def search_all_sources(query: str) -> List[AppResult]:
    query = (query or "").strip()
    if not query:
        return []

    cached = await _query_cache_get(query)
    if cached is not None:
        return cached[:MAX_RESULTS_TOTAL]

    local = _local_results_from_apps(search_apps(query))

    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    timeout = aiohttp.ClientTimeout(total=30, connect=20, sock_read=20)

    async with _SEARCH_SEM:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers, connector=aiohttp.TCPConnector(ssl=False)) as session:
            tasks = [
                _provider_aptoide(session, query, limit=PROVIDER_LIMIT),
                _provider_fdroid(session, query, limit=PROVIDER_LIMIT),
                _provider_openapk(session, query, limit=PROVIDER_LIMIT),
                _provider_apkmirror(session, query, limit=PROVIDER_LIMIT),
                _provider_izzy(session, query, limit=PROVIDER_LIMIT),
            ]
            results_lists = await asyncio.gather(*tasks, return_exceptions=True)

    merged: List[AppResult] = []
    merged.extend(local)

    for r in results_lists:
        if isinstance(r, Exception):
            logger.warning(f"Search provider error: {r}")
            continue
        merged.extend(r)

    deduped = _dedupe_results(merged)

    deduped.sort(
        key=lambda x: (
            -_relevance_score(query, x),
            SOURCE_ORDER.get(x.source, 99),
            x.title.lower(),
        )
    )
    final_results = deduped[:MAX_RESULTS_TOTAL]
    await _query_cache_put(query, final_results)
    return _clone_results(final_results)


# ==================== ساخت کیبورد نتایج (با صفحه‌بندی) ====================
def create_results_keyboard(token: str, results: List[AppResult], page: int = 0) -> InlineKeyboardMarkup:
    total = len(results)
    entry = SEARCH_CACHE.get(token)
    visible_total = total
    try:
        if entry and isinstance(entry.visible_count, int):
            visible_total = max(0, min(total, int(entry.visible_count)))
    except Exception:
        visible_total = total

    page = max(0, page)
    start = page * RESULTS_PER_PAGE
    if visible_total <= 0:
        start = 0
        page = 0
    elif start >= visible_total:
        page = max(0, (visible_total - 1) // RESULTS_PER_PAGE)
        start = page * RESULTS_PER_PAGE
    end = min(visible_total, start + RESULTS_PER_PAGE)

    keyboard: List[List[InlineKeyboardButton]] = []

    for idx in range(start, end):
        r = results[idx]
        # Do not show the source/site in UI (user preference).
        icon = "📦"
        btn_text = f"{idx+1}. {icon} {_truncate(r.title, 30)}"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"sel:{token}:{idx}")])

    nav_row: List[InlineKeyboardButton] = []
    if start > 0:
        nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"page:{token}:{page-1}"))
    if end < visible_total:
        nav_row.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"page:{token}:{page+1}"))
    if nav_row:
        keyboard.append(nav_row)

    # Lazy reveal: show 50 more results each time (after initial 100).
    if visible_total < total and end >= visible_total:
        keyboard.append([InlineKeyboardButton("➕ ۵۰ تای دیگه", callback_data=f"more50:{token}")])

    keyboard.append([InlineKeyboardButton("🔍 جستجوی جدید", callback_data="new_search")])
    keyboard.append([InlineKeyboardButton("📁 دسته‌بندی‌ها", callback_data="show_cats")])
    keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")])

    return InlineKeyboardMarkup(keyboard)

# ==================== تابع دانلود فایل ====================
async def download_file(
    app,
    *,
    progress_cb: Optional[Callable[[int, Optional[int]], Awaitable[None]]] = None,
):
    """دانلود فایل APK"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br'
        }
        
        timeout = aiohttp.ClientTimeout(total=60, connect=30, sock_read=30)
        
        async with aiohttp.ClientSession(
            timeout=timeout, 
            headers=headers,
            connector=aiohttp.TCPConnector(ssl=False)
        ) as session:
            
            async with session.get(app['url']) as response:
                if response.status == 200:
                    # ایجاد فایل موقت
                    temp_file = tempfile.NamedTemporaryFile(
                        delete=False, 
                        suffix='.apk',
                        prefix=f"download_{app['name'][:10]}_"
                    )
                    
                    # دانلود فایل
                    total_size = 0
                    expected_total: Optional[int] = None
                    try:
                        cl = response.headers.get("Content-Length")
                        if cl and str(cl).isdigit():
                            expected_total = int(cl)
                    except Exception:
                        expected_total = None

                    if progress_cb:
                        try:
                            await progress_cb(0, expected_total)
                        except Exception:
                            pass
                    chunk_size = 8192
                    
                    async for chunk in response.content.iter_chunked(chunk_size):
                        if chunk:
                            temp_file.write(chunk)
                            total_size += len(chunk)
                            if progress_cb:
                                try:
                                    await progress_cb(total_size, expected_total)
                                except Exception:
                                    pass
                    
                    temp_file.close()
                    
                    if total_size > 1024:  # حداقل 1KB
                        return temp_file.name, total_size
                    else:
                        os.unlink(temp_file.name)
                        return None, 0
                else:
                    return None, 0
                    
    except Exception as e:
        logger.error(f"خطا در دانلود {app['name']}: {e}")
        return None, 0

# ==================== هندلرهای بات ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع بات"""
    await _track_user(update, increment=0)
    if not await _ensure_channel_member(update, context, prompt_in_chat=True):
        return
    user = update.effective_user
    welcome_text = f"""
🤖 **سلام {user.first_name} عزیز!**

🎯 **به بات دانلود اپلیکیشن خوش آمدید**

📱 **من می‌توانم برنامه‌ها را مستقیماً در تلگرام برای شما ارسال کنم!**

🔍 **برای شروع:**
• نام برنامه را تایپ کنید (مثلاً: vpn)
• یا از دسته‌بندی‌ها انتخاب کنید

✅ **برنامه‌های موجود:**
•  فیلتر شکن های مختلف
• پیام‌رسان‌ها
• شبکه‌های اجتماعی
• و...

✨ **نکته مهم:**\n• اگر فایل خیلی بزرگ باشد، ممکن است تلگرام اجازه ارسال ندهد.
    """
    if _is_admin_user(update.effective_user.id if update.effective_user else None):
        # Admin: show ALL controls under textbox (reply keyboard), no inline menu.
        await update.message.reply_text(
            welcome_text,
            reply_markup=_build_admin_reply_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Normal users: inline menu only, no reply keyboard.
    await update.message.reply_text(
        welcome_text,
        reply_markup=_build_user_inline_menu(),
        parse_mode=ParseMode.MARKDOWN,
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام کاربر"""
    if not await _ensure_channel_member(update, context, prompt_in_chat=True):
        return
    query = update.message.text.strip()

    # Admin actions
    if _is_admin_user(update.effective_user.id if update.effective_user else None):
        if query == KB_SEARCH:
            await update.message.reply_text("🔍 **نام برنامه مورد نظر خود را تایپ کنید:**", parse_mode=ParseMode.MARKDOWN)
            return
        if query == KB_CATEGORIES:
            await _send_categories_message(int(update.effective_chat.id), context)
            return
        if query == KB_HELP:
            await help_command(update, context)
            return
        if query == ADMIN_KB_STATS:
            async with _USERS_LOCK:
                db = _load_users_db()
            await update.message.reply_text(_build_user_stats_text(db))
            return
        if query == ADMIN_KB_USERS:
            async with _USERS_LOCK:
                db = _load_users_db()
            for chunk in _format_users_list_text(db):
                await update.message.reply_text(chunk)
            return
    
    if len(query) < 2:
        await update.message.reply_text("⚠️ لطفاً حداقل ۲ حرف وارد کنید!")
        return

    await _track_user(update, increment=1)
    
    # ذخیره کوئری
    context.user_data['last_query'] = query
    
    search_msg = await update.message.reply_text(
        f"🔍 **در حال جستجو برای '{query}' در چند سایت...**\n"
        "⏳ لطفاً صبر کنید...",
        parse_mode=ParseMode.MARKDOWN,
    )

    results = await search_all_sources(query)
    
    if not results:
        await search_msg.edit_text(
            f"❌ **نتیجه‌ای برای '{query}' پیدا نشد!**\n\n"
            "🎯 **برنامه‌های موجود:**\n"
            "• vpn (برای VPN‌ها)\n"
            "• تلگرام (برای تلگرام)\n"
            "• واتساپ (برای واتساپ)\n"
            "• اینستاگرام (برای اینستاگرام)\n\n"
            "💡 **یا مستقیماً نام برنامه را بنویسید.**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔍 جستجوی جدید", callback_data="new_search")],
                    [InlineKeyboardButton("📁 دسته‌بندی‌ها", callback_data="show_cats")],
                    [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
                ]
            ),
        )
        return

    _cleanup_search_cache()
    token = _new_token()
    SEARCH_CACHE[token] = SearchCacheEntry(
        user_id=update.effective_chat.id,
        query=query,
        created_at=time.time(),
        results=results,
        visible_count=min(len(results), int(INITIAL_VISIBLE_RESULTS)),
    )

    await _prefetch_page_sizes(results, 0)
    keyboard = create_results_keyboard(token, results, page=0)

    await search_msg.edit_text(
        _build_results_message_text(
            query=query,
            results=results,
            page=0,
            visible_total=min(len(results), int(INITIAL_VISIBLE_RESULTS)),
        ),
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش کلیک روی دکمه"""
    query = update.callback_query
    await query.answer()
    await _track_user(update, increment=0)
    
    data = query.data

    if data == CB_CHECK_JOIN:
        if await _ensure_channel_member(update, context, prompt_in_chat=False):
            try:
                await query.edit_message_text("✅ عضویت تایید شد. خوش آمدید!", disable_web_page_preview=True)
            except Exception:
                pass
            await start_callback(query, context)
        else:
            try:
                await query.answer("❌ هنوز عضو کانال نیستی.", show_alert=True)
            except Exception:
                pass
        return

    if not await _ensure_channel_member(update, context, prompt_in_chat=True):
        try:
            await query.answer("🔒 اول عضو کانال شو.", show_alert=True)
        except Exception:
            pass
        return
    
    if data == "search":
        await query.edit_message_text("🔍 **نام برنامه مورد نظر خود را تایپ کنید:**", parse_mode=ParseMode.MARKDOWN)
        return
    
    elif data == "show_cats":
        await show_categories(query, context)
        return
    
    elif data == "help":
        await show_help(query, context)
        return
    
    elif data == "new_search":
        await query.edit_message_text("🔍 **نام برنامه مورد نظر خود را تایپ کنید:**", parse_mode=ParseMode.MARKDOWN)
        return
    
    elif data == "main_menu":
        await start_callback(query, context)
        return

    elif data.startswith("more50:"):
        parts = data.split(":", 1)
        if len(parts) != 2:
            return
        token = parts[1]

        entry = SEARCH_CACHE.get(token)
        if not entry or entry.user_id != query.message.chat_id or time.time() - entry.created_at > SEARCH_CACHE_TTL:
            await query.edit_message_text(
                "❌ **این لیست منقضی شده!**\n🔍 لطفاً دوباره جستجو کنید.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        old_visible = entry.visible_count if isinstance(entry.visible_count, int) else len(entry.results)
        new_visible = min(len(entry.results), int(old_visible) + int(LOAD_MORE_STEP))
        entry.visible_count = new_visible

        # Jump to the first page of the newly revealed chunk (e.g. 101-110 after showing 1-100).
        new_page = max(0, int(old_visible) // int(RESULTS_PER_PAGE))
        await _prefetch_page_sizes(entry.results, new_page)
        keyboard = create_results_keyboard(token, entry.results, page=new_page)
        await query.edit_message_text(
            _build_results_message_text(
                query=entry.query,
                results=entry.results,
                page=new_page,
                visible_total=new_visible,
            ),
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    elif data.startswith("page:"):
        # صفحه‌بندی نتایج
        parts = data.split(":")
        if len(parts) != 3:
            return
        token = parts[1]
        try:
            page = int(parts[2])
        except ValueError:
            return

        entry = SEARCH_CACHE.get(token)
        if not entry or entry.user_id != query.message.chat_id or time.time() - entry.created_at > SEARCH_CACHE_TTL:
            await query.edit_message_text(
                "❌ **این لیست منقضی شده!**\n🔍 لطفاً دوباره جستجو کنید.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        visible_total = entry.visible_count if isinstance(entry.visible_count, int) else len(entry.results)
        if visible_total <= 0:
            page = 0
        else:
            last_page = max(0, (int(visible_total) - 1) // int(RESULTS_PER_PAGE))
            page = max(0, min(int(page), last_page))

        await _prefetch_page_sizes(entry.results, page)
        keyboard = create_results_keyboard(token, entry.results, page=page)
        await query.edit_message_text(
            _build_results_message_text(
                query=entry.query,
                results=entry.results,
                page=page,
                visible_total=visible_total,
            ),
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    elif data.startswith("sel:"):
        parts = data.split(":")
        if len(parts) != 3:
            return
        token = parts[1]
        try:
            idx = int(parts[2])
        except ValueError:
            return

        entry = SEARCH_CACHE.get(token)
        if not entry or entry.user_id != query.message.chat_id or time.time() - entry.created_at > SEARCH_CACHE_TTL:
            await query.answer("❌ لیست منقضی شده! دوباره جستجو کن.", show_alert=True)
            return

        if idx < 0 or idx >= len(entry.results):
            await query.answer("❌ مورد انتخاب‌شده معتبر نیست!", show_alert=True)
            return

        result = entry.results[idx]
        await _track_user(update, increment=1)
        await download_and_send_result(query, context, result)
        return
    
    elif data.startswith("app_"):
        # پردازش انتخاب برنامه
        parts = data.split("_")
        if len(parts) >= 3:
            app_idx = int(parts[1])
            search_query = "_".join(parts[2:]) if len(parts) > 2 else ""
            
            # جستجو برای یافتن برنامه
            if search_query:
                results = search_apps(search_query)
            else:
                # همه برنامه‌ها
                all_apps = []
                for cat in APP_DATABASE.values():
                    all_apps.extend(cat)
                results = all_apps
            
            if 0 <= app_idx < len(results):
                app = results[app_idx]
                await _track_user(update, increment=1)
                await download_and_send_app(query, context, app)
            else:
                await query.answer("❌ برنامه مورد نظر پیدا نشد!")
        return
    
    elif data.startswith("cat_"):
        # نمایش برنامه‌های دسته‌بندی
        category = data[4:]
        await show_category_apps_all(query, context, category)
        return


async def _resolve_download(session: aiohttp.ClientSession, result: AppResult) -> Tuple[Optional[str], str]:
    """
    بر اساس منبع، لینک دانلود نهایی را استخراج می‌کند.
    خروجی: (download_url, filename_hint)
    """
    kind = (result.meta or {}).get("kind")

    if kind == "direct":
        url = str(result.meta.get("download_url") or result.page_url or "").strip()
        if not url:
            return None, ""
        filename = _safe_filename(result.title)
        if not os.path.splitext(filename)[1]:
            filename += ".apk"
        return url, filename

    if kind == "fdroid":
        pkg = str(result.meta.get("package") or "").strip()
        if not pkg:
            return None, ""
        api_url = f"https://f-droid.org/api/v1/packages/{pkg}"
        try:
            data = await _fetch_json(session, api_url, timeout_s=20)
            vc = int((data or {}).get("suggestedVersionCode") or 0)
            if vc <= 0:
                return None, ""
            dl = f"https://f-droid.org/repo/{pkg}_{vc}.apk"
            return dl, f"{pkg}_{vc}.apk"
        except Exception as e:
            logger.warning(f"F-Droid resolve failed for {pkg}: {e}")
            return None, ""

    if kind == "openapk":
        app_url = str(result.meta.get("app_url") or result.page_url or "").strip()
        if not app_url:
            return None, ""

        # 1) app page -> اولین لینک نسخه
        html = await _fetch_text(session, app_url, timeout_s=25)
        m = re.search(r'href=\"(?P<ver>/[^\\\"]+/[^\\\"]+/apk/\\d+-version)\"', html)
        if not m:
            return None, ""
        ver_url = urljoin("https://www.openapk.net", m.group("ver"))

        # 2) version page -> لینک serve token
        vhtml = await _fetch_text(session, ver_url, timeout_s=25)
        m2 = re.search(r'href=\"(?P<serve>/serve/\\?token=[^\\\"]+)\"', vhtml)
        if not m2:
            return None, ""
        serve_url = urljoin("https://www.openapk.net", m2.group("serve"))

        filename = _safe_filename(result.title) + ".apk"
        return serve_url, filename

    if kind == "apkmirror":
        release_url = str(result.meta.get("release_url") or result.page_url or "").strip()
        if not release_url:
            return None, ""

        # 1) release page -> variant page
        html = await _fetch_text(session, release_url, timeout_s=30)
        variants = re.findall(r'href=\"([^\"]+android-apk-download/)\"', html)
        variant_href = ""
        for v in variants:
            if "#disqus_thread" in v:
                continue
            variant_href = v
            break
        if not variant_href and variants:
            variant_href = variants[0]
        if not variant_href:
            return None, ""
        variant_url = urljoin("https://www.apkmirror.com", variant_href)

        # 2) variant page -> download/?key=
        vhtml = await _fetch_text(session, variant_url, timeout_s=30)
        m = re.search(r'href=\"(?P<k>/apk/[^\"]+/download/\\?key=[^\"]+)\"', vhtml)
        if not m:
            return None, ""
        key_url = urljoin("https://www.apkmirror.com", m.group("k"))

        # 3) key page -> download.php?id=...&key=...
        khtml = await _fetch_text(session, key_url, timeout_s=30)
        m2 = re.search(r'href=\"(?P<dl>/wp-content/themes/APKMirror/download\\.php\\?id=[^\\\"]+)\"', khtml)
        if not m2:
            return None, ""
        download_php = urljoin("https://www.apkmirror.com", m2.group("dl"))

        filename = _safe_filename(result.title)
        if not os.path.splitext(filename)[1]:
            filename += ".apkm"
        return download_php, filename

    return None, ""


async def send_direct_link_result(context, chat_id: int, title: str, url: str, source: str) -> None:
    """اعلان خطا (بدون ارسال لینک)"""
    buttons: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🔍 جستجوی برنامه دیگر", callback_data="new_search")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ]

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "❌ **نتوانستم این فایل را در تلگرام ارسال کنم.**\n\n"
            f"✅ **{title}**\n"
            "💡 ممکن است فایل خیلی بزرگ باشد یا سایت اجازه دانلود مستقیم ندهد."
        ),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def download_and_send_result(query, context, result: AppResult):
    """دانلود و ارسال نتیجه انتخاب‌شده"""
    msg = None
    temp_file_path: Optional[str] = None
    download_url = ""
    sent_file_path: Optional[str] = None
    download_slot_acquired = False
    try:
        title = (result.title or "App").strip()
        title_html = html_lib.escape(title)
        size_hint = html_lib.escape(_result_size_text(result) or "-")

        msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "<b>⏳ در حال آماده‌سازی…</b>\n\n"
                f"📌 <b>{title_html}</b>\n"
                f"📦 حجم: {size_hint}\n"
                "📥 دانلود: <b>0%</b>\n"
                "⏳ لطفاً صبر کنید..."
            ),
            parse_mode=ParseMode.HTML,
        )

        # حذف پیام نتایج
        try:
            await query.message.delete()
        except Exception:
            pass

        await _DOWNLOAD_SEM.acquire()
        download_slot_acquired = True

        headers = {"User-Agent": DEFAULT_UA}
        timeout = aiohttp.ClientTimeout(total=60, connect=30, sock_read=60)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers, connector=aiohttp.TCPConnector(ssl=False)) as session:
            download_url, filename_hint = await _resolve_download(session, result)
            if not download_url:
                try:
                    await msg.delete()
                except Exception:
                    pass
                await send_direct_link_result(context, query.message.chat_id, title, result.page_url or "", result.source)
                return

            filename = filename_hint or _safe_filename(title)
            if not os.path.splitext(filename)[1]:
                filename += ".apk"

            expected_total_hint: Optional[int] = None
            try:
                cached = _size_cache_get(download_url)
                if cached:
                    expected_total_hint = cached
                else:
                    sb = result.meta.get("size_bytes")
                    if isinstance(sb, int) and sb > 0:
                        expected_total_hint = int(sb)

                if not expected_total_hint:
                    expected_total_hint = await _guess_content_length(session, download_url, timeout_s=18)
            except Exception:
                expected_total_hint = None

            if expected_total_hint and expected_total_hint > TELEGRAM_UPLOAD_LIMIT_BYTES:
                try:
                    await msg.delete()
                except Exception:
                    pass
                await send_direct_link_result(context, query.message.chat_id, title, download_url, result.source)
                return

            if expected_total_hint and not isinstance(result.meta.get("size_bytes"), int):
                try:
                    result.meta["size_bytes"] = int(expected_total_hint)
                except Exception:
                    pass
                try:
                    _size_cache_set(download_url, int(expected_total_hint))
                except Exception:
                    pass

            progress_state = {"t": 0.0, "p": -1}

            async def progress_cb(downloaded: int, total: Optional[int]) -> None:
                try:
                    now = time.time()
                    if now - float(progress_state["t"]) < 0.8:
                        return

                    effective_total = total or expected_total_hint
                    if effective_total and effective_total > 0:
                        percent = int(downloaded * 100 / effective_total)
                        if percent == int(progress_state["p"]) and now - float(progress_state["t"]) < 2.0:
                            return
                        progress_state["p"] = percent

                        bar_len = 10
                        filled = int(bar_len * percent / 100)
                        bar = "█" * filled + "░" * (bar_len - filled)
                        dl_text = _format_size(downloaded) or "0KB"
                        total_text = _format_size(effective_total) or "?"

                        text = (
                            "<b>⏳ در حال دانلود…</b>\n\n"
                            f"📌 <b>{title_html}</b>\n"
                            f"{bar} <b>{percent}%</b>\n"
                            f"📦 {dl_text} / {total_text}\n"
                            "⏳ لطفاً صبر کنید..."
                        )
                    else:
                        dl_text = _format_size(downloaded) or "0KB"
                        text = (
                            "<b>⏳ در حال دانلود…</b>\n\n"
                            f"📌 <b>{title_html}</b>\n"
                            f"📦 دانلود شده: {dl_text}\n"
                            "⏳ لطفاً صبر کنید..."
                        )

                    progress_state["t"] = now
                    await msg.edit_text(text=text, parse_mode=ParseMode.HTML)
                except Exception:
                    return

            file_size = 0
            final_url = ""
            content_type = ""

            # دانلود از سرور (با درصد پیشرفت)
            try:
                temp_file_path, file_size, final_url, content_type = await _download_to_tempfile(
                    session,
                    download_url,
                    timeout_s=600,
                    max_bytes=TELEGRAM_UPLOAD_LIMIT_BYTES,
                    progress_cb=progress_cb,
                )
            except Exception as e:
                logger.warning(f"Server download failed, trying Telegram URL send: {e}")
                temp_file_path = None

            # اگر حجم خیلی بزرگ باشد
            if not temp_file_path and isinstance(file_size, int) and file_size > TELEGRAM_UPLOAD_LIMIT_BYTES:
                try:
                    await msg.delete()
                except Exception:
                    pass
                await send_direct_link_result(context, query.message.chat_id, title, download_url, result.source)
                return

            # اگر دانلود شد، فایل را ارسال کن
            if temp_file_path and file_size > 0:
                try:
                    result.meta["size_bytes"] = int(file_size)
                except Exception:
                    pass
                try:
                    _size_cache_set(download_url, int(file_size))
                except Exception:
                    pass

                # تعیین پسوند درست
                if "application/vnd.apkm" in (content_type or "").lower():
                    if not filename.lower().endswith(".apkm"):
                        filename = os.path.splitext(filename)[0] + ".apkm"
                else:
                    if not os.path.splitext(filename)[1]:
                        filename += ".apk"

                try:
                    await msg.edit_text(
                        text=(
                            "<b>✅ دانلود کامل شد!</b>\n\n"
                            f"📌 <b>{title_html}</b>\n"
                            f"📦 حجم: {_format_size(file_size) or '-'}\n"
                            "📥 دانلود: <b>100%</b>\n"
                            "⏫ در حال ارسال به تلگرام…"
                        ),
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass

                caption = (
                    "<b>✅ دانلود آماده شد!</b>\n\n"
                    f"<b>📌 نام:</b> {title_html}\n"
                    f"<b>📦 حجم:</b> {_format_size(file_size) or '-'}\n"
                )

                with open(temp_file_path, "rb") as f:
                    await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=f,
                        filename=filename,
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                        read_timeout=TELEGRAM_READ_TIMEOUT,
                        write_timeout=TELEGRAM_WRITE_TIMEOUT,
                    )

                sent_file_path = temp_file_path
                _schedule_delete_file(sent_file_path, DELETE_AFTER_SEND_SECONDS)
                temp_file_path = None

                try:
                    await msg.delete()
                except Exception:
                    pass

                keyboard = [
                    [InlineKeyboardButton("🔍 جستجوی برنامه دیگر", callback_data="new_search")],
                    [InlineKeyboardButton("📁 دسته‌بندی‌ها", callback_data="show_cats")],
                    [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
                ]
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="🎉 **فایل با موفقیت ارسال شد!**\n\n🔍 برای دانلود برنامه دیگر، دوباره جستجو کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

            # اگر دانلود سرور نشد، به عنوان آخرین تلاش بگذار تلگرام از URL دانلود کند (بدون درصد)
            try:
                await msg.edit_text(
                    text=(
                        "<b>⏫ در حال ارسال…</b>\n\n"
                        f"📌 <b>{title_html}</b>\n"
                        "⏳ لطفاً صبر کنید..."
                    ),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

            caption_url = (
                "<b>✅ ارسال فایل</b>\n\n"
                f"<b>📌 نام:</b> {title_html}\n"
                f"<b>📦 حجم:</b> {html_lib.escape(_result_size_text(result) or '-')}\n"
            )

            await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=download_url,
                filename=filename,
                caption=caption_url,
                parse_mode=ParseMode.HTML,
                read_timeout=TELEGRAM_READ_TIMEOUT,
                write_timeout=TELEGRAM_WRITE_TIMEOUT,
            )

            try:
                await msg.delete()
            except Exception:
                pass

            keyboard = [
                [InlineKeyboardButton("🔍 جستجوی برنامه دیگر", callback_data="new_search")],
                [InlineKeyboardButton("📁 دسته‌بندی‌ها", callback_data="show_cats")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
            ]
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="🎉 **فایل با موفقیت ارسال شد!**\n\n🔍 برای دانلود برنامه دیگر، دوباره جستجو کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    except Exception as e:
        logger.error(f"خطای کلی (download_and_send_result): {e}")
        try:
            if msg:
                await msg.delete()
        except Exception:
            pass
        await send_direct_link_result(context, query.message.chat_id, result.title, result.page_url or download_url, result.source)
    finally:
        if download_slot_acquired:
            try:
                _DOWNLOAD_SEM.release()
            except Exception:
                pass
        if temp_file_path:
            try:
                os.unlink(temp_file_path)
            except Exception:
                pass

async def download_and_send_app(query, context, app):
    """دانلود و ارسال برنامه"""
    msg = None
    temp_file_path: Optional[str] = None
    download_slot_acquired = False
    try:
        # پیام در حال دانلود
        app_name = str(app.get("name") or "App")
        app_name_html = html_lib.escape(app_name)
        size_label = html_lib.escape(str(app.get("size") or "-"))
        msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "<b>⏳ در حال آماده‌سازی…</b>\n\n"
                f"📌 <b>{app_name_html}</b>\n"
                f"📦 حجم: {size_label}\n"
                "📥 دانلود: <b>0%</b>\n"
                "⏳ لطفاً صبر کنید..."
            ),
            parse_mode=ParseMode.HTML,
        )

        # حذف پیام قبلی (لیست/منو)
        try:
            await query.message.delete()
        except Exception:
            pass

        progress_state = {"t": 0.0, "p": -1}

        async def progress_cb(downloaded: int, total: Optional[int]) -> None:
            try:
                now = time.time()
                if now - float(progress_state["t"]) < 0.8:
                    return

                if total and total > 0:
                    percent = int(downloaded * 100 / total)
                    if percent == int(progress_state["p"]) and now - float(progress_state["t"]) < 2.0:
                        return
                    progress_state["p"] = percent

                    bar_len = 10
                    filled = int(bar_len * percent / 100)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    dl_text = _format_size(downloaded) or "0KB"
                    total_text = _format_size(total) or "?"

                    text = (
                        "<b>⏳ در حال دانلود…</b>\n\n"
                        f"📌 <b>{app_name_html}</b>\n"
                        f"{bar} <b>{percent}%</b>\n"
                        f"📦 {dl_text} / {total_text}\n"
                        "⏳ لطفاً صبر کنید..."
                    )
                else:
                    dl_text = _format_size(downloaded) or "0KB"
                    text = (
                        "<b>⏳ در حال دانلود…</b>\n\n"
                        f"📌 <b>{app_name_html}</b>\n"
                        f"📦 دانلود شده: {dl_text}\n"
                        "⏳ لطفاً صبر کنید..."
                    )

                progress_state["t"] = now
                if msg:
                    await msg.edit_text(text=text, parse_mode=ParseMode.HTML)
            except Exception:
                return

        await _DOWNLOAD_SEM.acquire()
        download_slot_acquired = True

        temp_file_path, file_size = await download_file(app, progress_cb=progress_cb)

        if not temp_file_path or file_size <= 0:
            if msg:
                try:
                    await msg.delete()
                except Exception:
                    pass
            await send_direct_link(context, query.message.chat_id, app)
            return

        try:
            if msg:
                await msg.edit_text(
                    text=(
                        "<b>✅ دانلود کامل شد!</b>\n\n"
                        f"📌 <b>{app_name_html}</b>\n"
                        f"📦 حجم: {_format_size(file_size) or size_label}\n"
                        "📥 دانلود: <b>100%</b>\n"
                        "⏫ در حال ارسال به تلگرام…"
                    ),
                    parse_mode=ParseMode.HTML,
                )
        except Exception:
            pass

        with open(temp_file_path, "rb") as file:
            await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=file,
                filename=f"{app_name.replace(' ', '_')}.apk",
                caption=(
                    f"✅ **{app_name}**\n\n"
                    f"📦 حجم: {app.get('size','-')}\n"
                    f"🔄 نسخه: {app.get('version','-')}\n"
                    f"⭐ امتیاز: {app.get('rating','-')}\n\n"
                    f"📝 توضیحات:\n{app.get('description','-')}\n\n"
                    "📌 راهنمای نصب:\n"
                    "1) فایل را دانلود کنید\n"
                    "2) Settings → Security → Unknown Sources را فعال کنید\n"
                    "3) فایل را باز کنید و نصب کنید\n"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )

        # Delete the downloaded file after a delay (privacy + user request).
        _schedule_delete_file(temp_file_path, DELETE_AFTER_SEND_SECONDS)
        temp_file_path = None

        # حذف پیام دانلود
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass

        keyboard = [
            [InlineKeyboardButton("🔍 جستجوی برنامه دیگر", callback_data="new_search")],
            [InlineKeyboardButton("📚 دسته‌بندی‌ها", callback_data="show_cats")],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
        ]
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "🎉 **برنامه با موفقیت ارسال شد!**\n\n"
                "🧹 برای حفظ حریم خصوصی، فایل **۱ دقیقه بعد** از سرور پاک می‌شود.\n\n"
                "🔍 برای دانلود برنامه‌ی دیگر:"
            ),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN,
        )

    except Exception as e:
        logger.error(f"خطای کلی (download_and_send_app): {e}")
        if msg:
            try:
                await msg.delete()
            except Exception:
                pass
        await send_direct_link(context, query.message.chat_id, app)
    finally:
        if download_slot_acquired:
            try:
                _DOWNLOAD_SEM.release()
            except Exception:
                pass
        if temp_file_path:
            try:
                os.unlink(temp_file_path)
            except Exception:
                pass

async def send_direct_link(context, chat_id, app):
    """اعلان خطا (بدون ارسال لینک)"""
    app_name = str(app.get("name") or "App")
    size_label = str(app.get("size") or "-")

    keyboard = [
        [InlineKeyboardButton("🔍 جستجوی برنامه دیگر", callback_data="new_search")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ]

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "❌ **نتونستم فایل رو داخل تلگرام ارسال کنم.**\n\n"
            f"📦 **نام:** {app_name}\n"
            f"📦 **حجم:** {size_label}\n\n"
            "💡 ممکنه فایل خیلی بزرگ باشه یا لینک دانلود موقتاً مشکل داشته باشه.\n"
            "🔁 لطفاً دوباره تلاش کن یا برنامه‌ی دیگه‌ای رو جستجو کن."
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )

async def show_categories(query, context):
    """نمایش دسته‌بندی‌ها"""
    keyboard = []

    for category, label in CATEGORY_CATALOG:
        apps = APP_DATABASE.get(category) or []
        keyboard.append([InlineKeyboardButton(f"{label}", callback_data=f"cat_{category}")])
    
    keyboard.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")])
    
    await query.edit_message_text(
        "📚 **دسته‌بندی‌ها**\n\nروی هر دسته بزن تا لیست برنامه‌ها رو ببینی 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def show_category_apps(query, context, category):
    """نمایش برنامه‌های یک دسته"""
    if category not in APP_DATABASE:
        await query.answer("❌ این دسته‌بندی وجود ندارد!")
        return
    
    label = _category_label(category)
    apps = APP_DATABASE.get(category) or []

    # If the category is empty, do a live search to still provide results.
    if not apps:
        search_term = CATEGORY_SEARCH_QUERIES.get(category, label)
        await query.edit_message_text(
            f"🔍 **در حال جستجو برای '{label}'...**\n⏳ لطفاً صبر کنید...",
            parse_mode=ParseMode.MARKDOWN,
        )
        results = await search_all_sources(search_term)
        if not results:
            await query.edit_message_text(
                f"❌ **برای دسته '{label}' نتیجه‌ای پیدا نشد!**\n\n"
                "🔎 می‌تونی اسم برنامه رو مستقیم بفرستی یا دوباره تلاش کنی.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🔍 جستجوی جدید", callback_data="new_search")],
                        [InlineKeyboardButton("📚 دسته‌بندی‌ها", callback_data="show_cats")],
                        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
                    ]
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            return
    else:
        results = _local_results_from_apps(apps)

    _cleanup_search_cache()
    token = _new_token()
    SEARCH_CACHE[token] = SearchCacheEntry(
        user_id=query.message.chat_id,
        query=label,
        created_at=time.time(),
        results=results,
    )

    await _prefetch_page_sizes(results, 0)
    keyboard = create_results_keyboard(token, results, page=0)
    await query.edit_message_text(
        _build_results_message_text(
            query=label,
            results=results,
            page=0,
            visible_total=len(results),
        ),
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )

async def show_category_apps_all(query, context, category):
    """نمایش همه برنامه‌های مرتبط با یک دسته (جستجوی کامل)"""
    if category not in APP_DATABASE:
        await query.answer("❌ این دسته‌بندی وجود ندارد!")
        return

    label = _category_label(category)
    apps = APP_DATABASE.get(category) or []

    search_term = CATEGORY_SEARCH_QUERIES.get(category, label)
    await query.edit_message_text(
        f"🔍 **در حال جستجو برای '{label}'...**\n⏳ لطفاً صبر کنید...",
        parse_mode=ParseMode.MARKDOWN,
    )

    provider_results = await search_all_sources(search_term)
    local_results = _local_results_from_apps(apps)

    results = _dedupe_results(local_results + provider_results)

    if not results:
        await query.edit_message_text(
            f"❌ **برای دسته '{label}' نتیجه‌ای پیدا نشد!**\n\n"
            "🔎 می‌تونی اسم برنامه رو مستقیم بفرستی یا دوباره تلاش کنی.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔍 جستجوی جدید", callback_data="new_search")],
                    [InlineKeyboardButton("📚 دسته‌بندی‌ها", callback_data="show_cats")],
                    [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    _cleanup_search_cache()
    token = _new_token()
    SEARCH_CACHE[token] = SearchCacheEntry(
        user_id=query.message.chat_id,
        query=label,
        created_at=time.time(),
        results=results,
        visible_count=min(len(results), int(INITIAL_VISIBLE_RESULTS)),
    )

    await _prefetch_page_sizes(results, 0)
    keyboard = create_results_keyboard(token, results, page=0)
    await query.edit_message_text(
        _build_results_message_text(
            query=label,
            results=results,
            page=0,
            visible_total=min(len(results), int(INITIAL_VISIBLE_RESULTS)),
        ),
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )

async def show_help(query, context):
    """نمایش راهنما"""
    categories_line = "\n".join(f"• {label}" for _, label in CATEGORY_CATALOG[:15])
    help_text = f"""
❓ **راهنمای استفاده از بات**

🔎 **دانلود برنامه چطوریه؟**
1) اسم برنامه رو بفرست (مثلاً: `vpn` یا `telegram`)\n
2) از لیست نتایج، مورد دلخواه رو انتخاب کن\n
3) بات فایل APK رو دانلود می‌کنه و **مستقیم داخل تلگرام** می‌فرسته ✅

📚 **دسته‌بندی‌ها (حداقل ۱۵ دسته):**
{categories_line}

📲 **نصب فایل APK روی اندروید:**
1) فایل رو دانلود و باز کن\n
2) اگر خطا داد: Settings → Security → **Unknown Sources** رو فعال کن\n
3) نصب رو انجام بده و بعدش برای امنیت، Unknown Sources رو خاموش کن

⚠️ **نکته مهم:**
• اگر فایل خیلی بزرگ باشه، ممکنه تلگرام اجازه ارسال نده.\n
• بعد از ارسال فایل، برای حفظ حریم خصوصی **۱ دقیقه بعد** از سرور پاک می‌شه.
    """
    
    keyboard = [
        [InlineKeyboardButton("🔍 شروع جستجو", callback_data="search")],
        [InlineKeyboardButton("📁 دسته‌بندی‌ها", callback_data="show_cats")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")]
    ]
    
    await query.edit_message_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return

    categories_line = "\n".join(f"• {label}" for _, label in CATEGORY_CATALOG[:15])
    help_text = f"""
❓ **راهنمای استفاده از بات**

🔎 **دانلود برنامه چطوریه؟**
1) اسم برنامه رو بفرست (مثلاً: `vpn` یا `telegram`)\n
2) از لیست نتایج، مورد دلخواه رو انتخاب کن\n
3) بات فایل APK رو دانلود می‌کنه و **مستقیم داخل تلگرام** می‌فرسته ✅

📚 **دسته‌بندی‌ها:**
{categories_line}

⚠️ **نکته مهم:**
• بعد از ارسال فایل، برای حفظ حریم خصوصی **۱ دقیقه بعد** از سرور پاک می‌شه.
    """

    keyboard = [
        [InlineKeyboardButton("🔍 شروع جستجو", callback_data="search")],
        [InlineKeyboardButton("📚 دسته‌بندی‌ها", callback_data="show_cats")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ]

    await update.effective_message.reply_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def start_callback(query, context):
    """شروع بات از طریق callback"""
    user = query.from_user
    welcome_text = f"""
🤖 **سلام {user.first_name}!**

🎯 **بات دانلود اپلیکیشن آماده خدمت‌رسانی است**

📱 **ویژگی‌های بات:**
✅ دانلود مستقیم فایل‌ها در تلگرام
✅ دیتابیس کامل برنامه‌ها
✅ جستجوی هوشمند
✅ دسته‌بندی‌های منظم

🔍 **برای شروع، نام برنامه را بنویسید یا از گزینه‌های زیر استفاده کنید:**
"""
    
    try:
        if _is_admin_user(query.from_user.id if query.from_user else None):
            # Admin: remove inline menu and force reply-keyboard controls.
            await query.edit_message_text(welcome_text, parse_mode=ParseMode.MARKDOWN)
            if query.message:
                await _set_admin_reply_keyboard(context, int(query.message.chat_id))
            return
    except Exception:
        pass

    await query.edit_message_text(
        welcome_text,
        reply_markup=_build_user_inline_menu(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _CONFLICT_STOP_REQUESTED
    err = context.error
    if isinstance(err, Conflict):
        if _CONFLICT_STOP_REQUESTED:
            return
        _CONFLICT_STOP_REQUESTED = True
        logger.error(
            "409 Conflict: terminated by other getUpdates request; make sure that only one bot instance is running"
        )
        try:
            context.application.stop_running()
        except Exception:
            pass

# ==================== تابع اصلی ====================
def main():
    """تابع اصلی اجرای بات"""
    print("=" * 70)
    print("🚀 **بات دانلود اپلیکیشن - نسخه پایدار**")
    print("✅ توسعه‌یافته با هوش مصنوعی DeepSeek")
    print("✅ بدون نیاز به تنظیمات پیچیده")
    print("=" * 70)
    print(f"📅 تاریخ اجرا: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("⏳ در حال راه‌اندازی بات...\n")

    backoff_s = 5
    max_backoff_s = 300

    while True:
        try:
            # ساخت اپلیکیشن بدون پروکسی (ساده‌تر)
            app = (
                Application.builder()
                .token(TOKEN)
                .connect_timeout(30.0)
                .read_timeout(30.0)
                .write_timeout(30.0)
                .pool_timeout(30.0)
                .build()
            )

            # ثبت هندلرها
            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("help", help_command))

            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
            app.add_handler(CallbackQueryHandler(button_handler))
            app.add_error_handler(on_error)

            print("✅ هندلرها با موفقیت ثبت شدند")
            print("🤖 بات آماده دریافت پیام...")
            print("\n" + "=" * 70)
            print("📱 **برای خروج: Ctrl + C**")
            print("=" * 70)
            print("\n💡 **نکته:** اگر بات اجرا نشد:")
            print("1. اتصال اینترنت خود را بررسی کنید")
            print("2. از VPN استفاده کنید")
            print("3. روی سرور خارج اجرا کنید")
            print("\n")

            # Python 3.12+ may not create a default event loop automatically.
            # Ensure one exists for python-telegram-bot run_polling (avoids: no current event loop).
            try:
                asyncio.get_event_loop()
            except RuntimeError:
                asyncio.set_event_loop(asyncio.new_event_loop())

            # اجرای بات
            app.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                close_loop=False
            )

            # If run_polling exits cleanly, reset backoff and restart.
            backoff_s = 5

        except KeyboardInterrupt:
            print("\n🛑 خروج با دستور کاربر")
            break
        except Exception as e:
            print(f"\n❌ **خطا در اجرای بات:** {e}")
            print(f"🔄 بات پس از {backoff_s} ثانیه دوباره راه‌اندازی می‌شود...")
            time.sleep(backoff_s)
            backoff_s = min(max_backoff_s, backoff_s * 2)
            continue

# ==================== اجرای برنامه ====================
if __name__ == "__main__":
    main()
