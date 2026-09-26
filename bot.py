"""Professional Arabic TikTok Info Telegram Bot.

Features: full public profile card, HD avatar, account level, engagement rate,
account comparison, favorites, growth tracking, live monitoring & alerts
(new video / deleted videos / name change / follower spikes), no-watermark
video download, and a Telegram Stars VIP subscription + admin tools.
"""
import os
import logging
import asyncio
import difflib
import httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    LabeledPrice,
    InputMediaPhoto,
    BotCommand,
)
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from telegram.error import RetryAfter, TimedOut, NetworkError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ChatJoinRequestHandler,
    ContextTypes,
    filters,
)

import tiktok_service as tk
import formatting as F
import reports as R
import i18n

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "6641619062"))
SUPPORT_ID = 6641619062
SUPPORT_USERNAME = "DRK450"
SUPPORT_URL = f"https://t.me/{SUPPORT_USERNAME}"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
DEVELOPER = os.environ.get("DEVELOPER", "DRK450").lstrip("@")
ADMIN_SESSIONS: set[int] = set()
PRICE_MONTH = int(os.environ.get("VIP_PRICE_MONTH", "250"))
PRICE_LIFE = int(os.environ.get("VIP_PRICE_LIFETIME", "1500"))
INTERVAL = int(os.environ.get("MONITOR_INTERVAL_MIN", "30"))
FREE_LIMIT = int(os.environ.get("FREE_DAILY_LIMIT", "15"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("tiktokbot")

import certifi
client = AsyncIOMotorClient(os.environ["MONGO_URL"], tlsCAFile=certifi.where(), maxPoolSize=100, minPoolSize=10)
db = client[os.environ["DB_NAME"]]

# High-load in-memory cache
KNOWN_USERS: set[int] = set()
LAST_START_TIMES: dict[int, float] = {}

USER_SAVE_SEM = asyncio.Semaphore(25)

async def _save_user_background(tid: int, tg_user):
    async with USER_SAVE_SEM:
        try:
            await db.users.update_one(
                {"telegram_id": tid},
                {
                    "$setOnInsert": {
                        "telegram_id": tid,
                        "username": getattr(tg_user, "username", None),
                        "first_name": getattr(tg_user, "first_name", None),
                        "is_vip": False,
                        "vip_until": None,
                        "favorites": [],
                        "joined_at": now().isoformat(),
                        "searches": 0,
                        "search_day": "",
                        "day_count": 0,
                    }
                },
                upsert=True,
            )
        except Exception as e:
            log.warning("Background user save failed for %s: %s", tid, e)

async def _record_web_conversion():
    try:
        await db.web_stats.update_one({"_id": "global"}, {"$inc": {"conversions": 1}}, upsert=True)
    except Exception as e:
        log.warning("Failed to record web conversion: %s", e)

async def _save_user_lang_bg(tid: int, lang: str):
    try:
        await db.users.update_one({"telegram_id": tid}, {"$set": {"lang": lang}}, upsert=True)
    except Exception as e:
        log.warning("Failed to save user lang for %s: %s", tid, e)

async def _handle_referral(tid: int, arg: str, bot_instance):
    try:
        ref = int(arg[4:])
        if ref and ref != tid and (ref in KNOWN_USERS or await db.users.find_one({"telegram_id": ref})):
            await db.users.update_one({"telegram_id": tid}, {"$set": {"referred_by": ref}})
            await db.users.update_one({"telegram_id": ref}, {"$inc": {"invites": 1}})
            ref_user = await db.users.find_one({"telegram_id": ref})
            invites = ref_user.get("invites", 1) if ref_user else 1
            try:
                await bot_instance.send_message(
                    ref,
                    f"🎁 <b>صديق جديد انضم عبر رابطك!</b> (إجمالي دعواتك: {invites})",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
    except Exception:
        pass

# ------------------------- reply keyboard -------------------------
BTN_SEARCH = "🔍 بحث عن حساب"
BTN_MON = "🔔 مراقبتي"
BTN_DL = "🎬 تحميل فيديو"
BTN_HELP = "ℹ️ مساعدة"
BTN_INVITE = "🎁 دعوة الأصدقاء"
BTN_AGENCY = "🏢 لوحة الوكالة"
BTN_NOTICE = "⚠️ تنبيه هام"

MAIN_KB = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("بحث عن حساب", callback_data="main_search", icon_custom_emoji_id="5217871625206132326"),
        InlineKeyboardButton("تحميل فيديو", callback_data="main_dl", icon_custom_emoji_id="5215714349032678015")
    ],
    [
        InlineKeyboardButton("الحسابات المراقبة", callback_data="main_mon", icon_custom_emoji_id="6037397706505195857"),
        InlineKeyboardButton("دعوة الأصدقاء", callback_data="main_invite", icon_custom_emoji_id="6048721430730773527")
    ],
    [
        InlineKeyboardButton("تنبيه هام", callback_data="main_notice", icon_custom_emoji_id="6100496806217517918")
    ]
])

START_TEXT = (
    "🎵 <b>أهلاً بك في بوت معلومات تيك توك</b>\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "أرسل <b>اسم مستخدم</b> أو <b>رابط حساب</b> تيك توك، وأعطيك <tg-emoji emoji-id=\"5014902839575577394\">🆔</tg-emoji> بطاقة معلومات كاملة.\n\n"
    "<tg-emoji emoji-id=\"5217871625206132326\">🔎</tg-emoji> مثال: <code>@tiktok</code>\n"
    "<tg-emoji emoji-id=\"5254008401997869778\">🎬</tg-emoji> أرسل رابط فيديو لتحميله بدون علامة مائية.\n\n"
    "✨ <b>مميزات البوت المجانية بالكامل:</b>\n"
    "• <tg-emoji emoji-id=\"5179271173568988234\">📈</tg-emoji> تتبّع نمو الحسابات والمتابعين\n"
    "• 🔔 مراقبة لحظية وتنبيهات التغيير\n"
    "• ⚖️ مقارنة الحسابات والتقارير وتحميل الصور\n"
    "• 🎧 الدعم الفني: /support\n\n"
)

REF_REWARD_DAYS = 3
AGENCY_MAX = 50


def now():
    return datetime.now(timezone.utc)


async def _download_bytes(url: str) -> bytes | None:
    """Download binary content (photo or video) with proper TikTok headers."""
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
        "Referer": "https://www.tiktok.com/",
    }
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="safari15_5") as s:
            r = await s.get(url, headers=headers, timeout=20)
            if r.status_code == 200 and r.content:
                return r.content
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as cx:
            r = await cx.get(url, headers=headers)
            if r.status_code == 200 and r.content:
                return r.content
    except Exception:
        pass
    return None


# ------------------------- db helpers -------------------------
async def get_user(tid: int, tg=None) -> dict:
    u = await db.users.find_one({"telegram_id": tid})
    if not u:
        u = {
            "telegram_id": tid,
            "username": getattr(tg, "username", None),
            "first_name": getattr(tg, "first_name", None),
            "is_vip": False,
            "vip_until": None,
            "favorites": [],
            "joined_at": now().isoformat(),
            "searches": 0,
            "search_day": "",
            "day_count": 0,
        }
        await db.users.insert_one(u)
    return u


async def is_vip(tid: int) -> bool:
    return True


async def cache_audio(video_id: str, music_url: str, title: str = ""):
    if video_id and music_url:
        await db.audio_cache.update_one(
            {"video_id": str(video_id)},
            {"$set": {"music_url": music_url, "title": title}},
            upsert=True
        )


async def grant_vip(tid: int, days: int | None):
    until = None if days is None else (now() + timedelta(days=days)).isoformat()
    await db.users.update_one(
        {"telegram_id": tid},
        {"$set": {"is_vip": True, "vip_until": until}},
        upsert=True,
    )


async def _extend_vip(tid: int, days: int):
    """Add days to VIP, stacking onto current expiry (keeps lifetime intact)."""
    u = await db.users.find_one({"telegram_id": tid}) or {}
    if u.get("is_vip") and u.get("vip_until") is None:
        return  # lifetime, nothing to extend
    base = now()
    vu = u.get("vip_until")
    if vu:
        try:
            cur = datetime.fromisoformat(vu)
            if cur > base:
                base = cur
        except Exception:
            pass
    await db.users.update_one(
        {"telegram_id": tid},
        {"$set": {"is_vip": True, "vip_until": (base + timedelta(days=days)).isoformat()}},
        upsert=True,
    )


async def check_free_quota(tid: int) -> bool:
    # All features are completely free and unlimited for all users
    await db.users.update_one(
        {"telegram_id": tid},
        {"$inc": {"searches": 1}},
        upsert=True,
    )
    return True


async def store_snapshot(p: dict, force=False):
    uid = p.get("uniqueId")
    if not uid:
        return
    last = await db.snapshots.find_one({"uniqueId": uid}, sort=[("ts", -1)])
    if last and not force:
        try:
            if datetime.fromisoformat(last["ts"]) > now() - timedelta(hours=1):
                return
        except Exception:
            pass
    await db.snapshots.insert_one({
        "uniqueId": uid,
        "ts": now().isoformat(),
        "followerCount": p.get("followerCount"),
        "followingCount": p.get("followingCount"),
        "heartCount": p.get("heartCount"),
        "videoCount": p.get("videoCount"),
        "nickname": p.get("nickname"),
    })


# ------------------------- keyboards -------------------------
def account_kb(uid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 الصورة HD", callback_data=f"img:{uid}"),
         InlineKeyboardButton("🏆 مستوى الحساب", callback_data=f"level:{uid}")],
        [InlineKeyboardButton("📊 معدل التفاعل", callback_data=f"er:{uid}"),
         InlineKeyboardButton("📈 تتبّع النمو", callback_data=f"growth:{uid}")],
        [InlineKeyboardButton("📄 تقرير PDF", callback_data=f"pdf:{uid}"),
         InlineKeyboardButton("🛡 كشف المقلّدين", callback_data=f"imp:{uid}")],
        [InlineKeyboardButton("📸 مشاهدة الستوري", callback_data=f"story:{uid}"),
         InlineKeyboardButton("⭐ أبرز القصص", callback_data=f"high:{uid}")],
        [InlineKeyboardButton("🔔 مراقبة الحساب", callback_data=f"monitor:{uid}"),
         InlineKeyboardButton("⚖️ مقارنة الحسابات", callback_data=f"compare:{uid}")],
        [InlineKeyboardButton("💰 القيمة المالية للحساب", callback_data=f"val_calc:{uid}"),
         InlineKeyboardButton("🔄 تحديث البيانات", callback_data=f"refresh:{uid}")],
    ])


# ------------------------- commands -------------------------
async def get_effective_lang(context: ContextTypes.DEFAULT_TYPE, user) -> str:
    lang = context.user_data.get("lang") if context and context.user_data else None
    if not lang and user:
        lang = i18n.detect_lang(getattr(user, "language_code", None))
        if context and context.user_data is not None:
            context.user_data["lang"] = lang
    return lang or "ar"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    tid = user.id

    args = getattr(context, "args", None)
    if args and args[0].startswith("web"):
        asyncio.create_task(_record_web_conversion())

    # Fast in-memory check: zero database round-trips for existing users
    if tid not in KNOWN_USERS:
        KNOWN_USERS.add(tid)
        asyncio.create_task(_save_user_background(tid, user))
        if args and args[0].startswith("ref_"):
            asyncio.create_task(_handle_referral(tid, args[0], context.bot))

    if not await ensure_subscribed(update, context):
        return

    user_lang = await get_effective_lang(context, user)
    start_text = i18n.get_start_text(user_lang)
    main_kb = i18n.get_main_keyboard(user_lang)

    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        try:
            await update.callback_query.message.edit_text(start_text, parse_mode=ParseMode.HTML, reply_markup=main_kb)
            return
        except Exception:
            pass

    try:
        await update.effective_message.reply_text(start_text, parse_mode=ParseMode.HTML, reply_markup=main_kb)
    except Exception:
        # Resilient fallback without parse_mode
        await update.effective_message.reply_text(start_text, reply_markup=main_kb)


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Automatically approve chat join requests instantly and welcome the user in their language."""
    req = update.chat_join_request
    if not req:
        return
    try:
        await req.approve()
        log.info("Auto-approved join request: user %s in chat %s", req.user_chat_id, req.chat.id)
        tid = req.user_chat_id
        if tid not in KNOWN_USERS:
            KNOWN_USERS.add(tid)
            asyncio.create_task(_save_user_background(tid, req.from_user))
        user_lang = i18n.detect_lang(getattr(req.from_user, "language_code", None))
        start_text = i18n.get_start_text(user_lang)
        main_kb = i18n.get_main_keyboard(user_lang)

        async def _send_welcome_bg():
            try:
                await context.bot.send_message(
                    chat_id=tid,
                    text=start_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=main_kb,
                )
            except Exception:
                try:
                    await context.bot.send_message(
                        chat_id=tid,
                        text=start_text,
                        reply_markup=main_kb,
                    )
                except Exception:
                    pass

        asyncio.create_task(_send_welcome_bg())
    except Exception as e:
        log.warning("Failed to auto-approve join request: %s", e)


async def support_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_lang = await get_effective_lang(context, user)
    txt = i18n.get_msg(user_lang, "support_text")
    kb = i18n.get_support_keyboard(user_lang, support_id=str(SUPPORT_ID))
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.message.edit_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
            return
        except Exception:
            pass
        try:
            await update.callback_query.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            await update.callback_query.message.reply_text(txt, reply_markup=kb)
    else:
        try:
            await update.effective_message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            await update.effective_message.reply_text(txt, reply_markup=kb)


async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_lang = await get_effective_lang(context, user)
    txt = i18n.get_msg(user_lang, "choose_lang")
    kb = i18n.get_language_selection_keyboard()
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.message.edit_text(txt, reply_markup=kb)
            return
        except Exception:
            pass
        await update.callback_query.message.reply_text(txt, reply_markup=kb)
    else:
        await update.effective_message.reply_text(txt, reply_markup=kb)


async def dev_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await support_cmd(update, context)


# ------------------------- core: show profile -------------------------
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str, edit=False):
    tid = update.effective_user.id
    await check_free_quota(tid)
    msg = update.callback_query.message if edit else update.message
    wait = await context.bot.send_message(tid, "⏳ جاري جلب المعلومات...")
    p = await tk.fetch_profile(username)
    await context.bot.delete_message(tid, wait.message_id)
    if not p:
        await context.bot.send_message(tid, "❌ لم أجد هذا الحساب. تأكد من اسم المستخدم.")
        return
    await store_snapshot(p)
    await context.bot.send_message(
        tid,
        F.profile_card(p),
        parse_mode=ParseMode.HTML,
        reply_markup=account_kb(p["uniqueId"]),
        disable_web_page_preview=True,
    )


async def do_download(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    tid = update.effective_user.id
    wait = await update.effective_message.reply_text("⏳ جاري تحميل الفيديو بدون علامة مائية...")
    data = await tk.download_video(url)
    try:
        await context.bot.delete_message(tid, wait.message_id)
    except Exception:
        pass
    if not data or (not data.get("play") and not data.get("images") and not data.get("video_path")):
        await update.effective_message.reply_text("❌ تعذّر تحميل المنشور. تأكد من الرابط.")
        return

    author = data.get("author", {})
    uid = author.get("unique_id", "")
    prof = await tk.fetch_profile(uid) if uid else None

    likes = data.get("digg_count") or 0
    comments = data.get("comment_count") or 0
    saves = data.get("collect_count") or 0
    shares = data.get("share_count") or 0
    downloads = data.get("download_count") or 0
    views = data.get("play_count") or 0
    reposts = data.get("repost_count") or 0

    import datetime
    ts = data.get('create_time')
    if ts:
        dt = datetime.datetime.fromtimestamp(ts)
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")
    else:
        date_str = "—"
        time_str = "—"

    def _clean_str(s: str) -> str:
        if not s:
            return ""
        return "".join(ch for ch in str(s) if ch not in ("\ufffc", "\ufffd") and not (0x200B <= ord(ch) <= 0x200F)).strip()

    raw_nick = _clean_str(data.get("author", {}).get("nickname", ""))
    if not raw_nick and prof:
        raw_nick = _clean_str(prof.get("nickname", ""))
    nickname = raw_nick or uid or "—"

    raw_bio = data.get("title") or ""
    if raw_bio.startswith("TikTok video #") or raw_bio.startswith("TikTok photo #"):
        raw_bio = ""
    bio = _clean_str(raw_bio) or "—"
    acc_id = prof.get("id", "—") if prof else "—"

    # caption: strictly as user requested
    lines = [
        f"🎬 <b>منشور تيك توك</b>",
        f"👤 اسم الحساب: {F.esc(nickname)}",
        f"👤 يوزر الحساب: @{F.esc(uid)}",
        f"🆔 ايدي الحساب: {F.esc(acc_id)}",
        f"📅 تاريخ نشر المنشور: {date_str}",
        f"⏰ توقيت النشر: {time_str}",
        f"📝 البايو الخاص بالمنشور: {F.esc(bio)}"
    ]

    cap = "\n".join(lines)


    rows = [
        [InlineKeyboardButton(f"👁 المشاهدات: {F.fmt_num(views)}", callback_data="noop")],
        [InlineKeyboardButton(f"❤️ الإعجابات: {F.fmt_num(likes)}", callback_data="noop")],
        [InlineKeyboardButton(f"💬 التعليقات: {F.fmt_num(comments)}", callback_data="noop")],
        [InlineKeyboardButton(f"🔖 الحفظ: {F.fmt_num(saves)}", callback_data="noop")],
        [InlineKeyboardButton(f"🔗 المشاركات: {F.fmt_num(shares)}", callback_data="noop")],
                [InlineKeyboardButton(f"⬇️ التنزيلات: {F.fmt_num(downloads)}", callback_data="noop")]
    ]
    music_url = (data.get("music_info") or {}).get("play") or data.get("music")
    video_id = data.get("id") or data.get("video_id")
    if isinstance(music_url, str) and music_url.startswith("http") and video_id:
        await cache_audio(str(video_id), music_url, title=(data.get("title") or "TikTok Audio"))
        rows.append([InlineKeyboardButton("🎵 تنزيل الأغنية (MP3)", callback_data=f"dl_audio:{video_id}")])
    if uid:
        rows.append([InlineKeyboardButton(f"👤 عرض حساب @{uid}", callback_data=f"open:{uid}")])
    kb = InlineKeyboardMarkup(rows)

    imgs = data.get("images") or []
    if imgs:
        media = []
        for i, u in enumerate(imgs[:10]):
            b = await _download_bytes(u)
            item_media = b if b else u
            if i == 0:
                media.append(InputMediaPhoto(media=item_media, caption=cap, parse_mode=ParseMode.HTML))
            else:
                media.append(InputMediaPhoto(media=item_media))
        try:
            if len(media) == 1:
                await context.bot.send_photo(tid, photo=media[0].media, caption=cap, parse_mode=ParseMode.HTML)
            else:
                await context.bot.send_media_group(tid, media=media)
            await context.bot.send_message(tid, "📊 إحصائيات وأدوات المنشور:", reply_markup=kb)
        except Exception as e:
            log.warning("Failed to send slideshow media group: %s", e)
            await update.effective_message.reply_text(
                cap + f"\n\n⚠️ تعذّر تحميل الصور تلقائياً كملفات، إليك رابط أول صورة:\n{imgs[0]}",
                parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True,
            )
        return

    video_path = data.get("video_path")
    try:
        if video_path and os.path.exists(video_path):
            with open(video_path, "rb") as vf:
                await context.bot.send_video(
                    tid, video=vf, caption=cap, parse_mode=ParseMode.HTML, reply_markup=kb
                )
        elif data.get("play"):
            try:
                await context.bot.send_video(
                    tid, video=data["play"], caption=cap, parse_mode=ParseMode.HTML, reply_markup=kb
                )
            except Exception:
                b = await _download_bytes(data["play"])
                if b:
                    await context.bot.send_video(
                        tid, video=b, caption=cap, parse_mode=ParseMode.HTML, reply_markup=kb
                    )
                else:
                    raise
        else:
            raise ValueError("No video source available")
    except Exception as e:
        log.warning("send_video error: %s", e)
        if data.get("play"):
            await update.effective_message.reply_text(
                cap + f"\n\n🔗 رابط التحميل:\n{data['play']}",
                parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True,
            )
        else:
            await update.effective_message.reply_text("❌ تعذّر إرسال الفيديو.")
    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass


# ------------------------- text router -------------------------
async def router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    text = (msg.text or msg.caption or "").strip()
    tid = update.effective_user.id

    if is_admin(tid):
        ADMIN_SESSIONS.add(tid)

    # ---- admin: pending states (password / broadcast / channel / grant) ----
    if msg.entities:
        for ent in msg.entities:
            if ent.type == "custom_emoji":
                await msg.reply_text(f"💡 ID الرمز التعبيري:\n`{ent.custom_emoji_id}`\n\n_اضغط لنسخه_", parse_mode="Markdown")
                return
    
    st = context.user_data.get("await")
    if st == "admin_pw":
        context.user_data.pop("await", None)
        if text == ADMIN_PASSWORD or is_admin(tid):
            ADMIN_SESSIONS.add(tid)
            return await admin_panel(update, context)
        return await msg.reply_text("❌ كلمة سر خاطئة.")
    if st == "broadcast" and is_admin(tid):
        context.user_data.pop("await", None)
        return await _do_broadcast(update, context)
    if st == "add_channel" and is_admin(tid):
        context.user_data.pop("await", None)
        return await _add_channel(update, context, text)
    if st == "grant" and is_admin(tid):
        context.user_data.pop("await", None)
        return await _do_grant(update, context, text)

    # ---- admin entry triggers ----
    if is_admin(tid) and text.lower() in ("صويري", "صوري", "ادمن", "الادمن", "admin", "/admin", "/panel", "لوحة التحكم"):
        ADMIN_SESSIONS.add(tid)
        return await admin_panel(update, context)

    if is_admin(tid) and text.lower() in ("اذاعة", "إذاعة", "اداعة", "broadcast", "/broadcast", "/bc"):
        ADMIN_SESSIONS.add(tid)
        context.user_data["await"] = "broadcast"
        return await msg.reply_text(
            "📢 <b>قسم الإذاعة الجماعية</b>\n\n"
            "أرسل الآن الرسالة (نص، صورة، فيديو، أو رسالة محولة) التي تريد إذاعتها لكل مستخدمي البوت:",
            parse_mode=ParseMode.HTML
        )

    if not text:
        return

    # ---- forced subscription gate (applies to everything below) ----
    if not await ensure_subscribed(update, context):
        return

    # ---- quick text navigation triggers ----
    if text.lower() in ("بدء", "start", "/start", "القائمة الرئيسية", "الرئيسية", "رجوع"):
        return await start(update, context)
    if text.lower() in ("الدعم الفني", "الدعم", "دعم", "/support", "support"):
        return await support_cmd(update, context)

    if tk.is_video_link(text):
        return await do_download(update, context, text)

    # compare second account
    if context.user_data.get("await") == "compare":
        context.user_data.pop("await", None)
        first = context.user_data.pop("compare_a", None)
        b = await tk.fetch_profile(text)
        a = await tk.fetch_profile(first) if first else None
        if not a or not b:
            await update.effective_message.reply_text("❌ تعذّر جلب أحد الحسابين.")
            return
        await update.effective_message.reply_text(F.compare_card(a, b), parse_mode=ParseMode.HTML)
        return

    await show_profile(update, context, text)


# ------------------------- Notice -------------------------
async def show_notice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "⚠️ <b>تنبيه هام حول الخدمة وأداء البوت</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "عزيزي المستخدم، نود إحاطتك بالنقاط التالية لضمان أفضل تجربة استخدام:\n\n"
        "⚡ <b>أداء البوت والسرعة:</b>\n"
        "بسبب الضغط الشديد على البوت وكثرة طلبات البحث والتحميل المتزامنة من المستخدمين، قد يواجه البوت بطئاً مؤقتاً في بعض الأوقات أثناء معالجة طلبك.\n\n"
        "❌ <b>حدوث أخطاء بسيطة:</b>\n"
        "قد تنتج أخطاء بسيطة وغير متوقعة أثناء تحميل مقاطع الفيديو، الصور، أو الستوري؛ وذلك نتيجة للتغييرات المستمرة التي تجريها خوادم تيك توك لحظر البوتات، أو بسبب الضغط الكبير على خادمنا.\n\n"
        "🔄 <b>ماذا تفعل في حال حدوث خطأ أو بطء؟</b>\n"
        "يرجى عدم تكرار إرسال الرابط عدة مرات متتالية. فقط انتظر <b>بضع دقائق</b> ثم أعد المحاولة مجدداً وسيعمل معك البوت بنجاح تام.\n\n"
        "شكراً لتفهمكم ودعمكم المستمر! ❤️"
    )
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(txt, parse_mode=ParseMode.HTML)


# ------------------------- Free Service Info -------------------------
async def show_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "🎉 <b>البوت مجاني بالكامل 100%!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "جميع مميزات البوت متاحة لجميع المستخدمين بلا أي قيود وبدون أي اشتراك مدفوع:\n\n"
        "• 🔍 بحث فوري وجلب بطاقة الحساب الكاملة\n"
        "• 🎬 تحميل الفيديوهات والصور بأعلى دقة وبدون علامة مائية\n"
        "• 🔔 مراقبة الحسابات والتنبيهات المباشرة والتلقائية\n"
        "• ⚖️ مقارنة الحسابات وتحليل معدل النمو والتفاعل\n"
        "• 📄 استخراج تقارير PDF احترافية متكاملة\n"
        "• 🛡 فحص وكشف الحسابات المنتحلة وتنبيهات الانتحال\n\n"
        "استمتع باستخدام كافة الميزات بلا حدود! ❤️"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 بحث عن حساب", callback_data="main_search"),
         InlineKeyboardButton("🎬 تحميل فيديو", callback_data="main_dl")],
    ])
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)


# ------------------------- monitors -------------------------
async def my_monitors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    mons = await db.monitors.find({"telegram_id": tid}).to_list(100)
    if not mons:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة حساب", callback_data="add_mon_prompt")]])
        await update.effective_message.reply_text(
            "🔔 لا يوجد حسابات مراقبة حالياً.", reply_markup=kb
        )
        return
    lines = "\n".join(f"• @{m['uniqueId']}" for m in mons)
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton(f"🗑 إيقاف @{m['uniqueId']}", callback_data=f"unmon:{m['uniqueId']}")] for m in mons]
    )
    await update.effective_message.reply_text(
        f"🔔 <b>حساباتك المراقبة</b>\n━━━━━━━━━━\n{lines}", parse_mode=ParseMode.HTML, reply_markup=kb
    )


# ------------------------- callbacks -------------------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tid = q.from_user.id
    data = q.data or ""
    action, _, arg = data.partition(":")

    user_lang = await get_effective_lang(context, q.from_user)

    if action not in ("checksub", "buy"):
        if not await ensure_subscribed(update, context):
            return

    if action == "buy":
        return await show_vip(update, context)

    if action == "set_lang":
        return await lang_cmd(update, context)

    if action == "lang":
        new_lang = arg if arg in i18n.SUPPORTED_LANGUAGES else "ar"
        if context and context.user_data is not None:
            context.user_data["lang"] = new_lang
        asyncio.create_task(_save_user_lang_bg(tid, new_lang))
        confirm_txt = i18n.get_msg(new_lang, "lang_selected")
        await q.answer(confirm_txt)
        start_txt = i18n.get_start_text(new_lang)
        kb = i18n.get_main_keyboard(new_lang)
        try:
            return await q.message.edit_text(start_txt, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            try:
                return await q.message.reply_text(start_txt, parse_mode=ParseMode.HTML, reply_markup=kb)
            except Exception:
                return await q.message.reply_text(start_txt, reply_markup=kb)

    if action in ("back_home", "main_back_start"):
        start_txt = i18n.get_start_text(user_lang)
        kb = i18n.get_main_keyboard(user_lang)
        try:
            return await q.message.edit_text(start_txt, parse_mode=ParseMode.HTML, reply_markup=kb)
        except Exception:
            try:
                return await q.message.reply_text(start_txt, parse_mode=ParseMode.HTML, reply_markup=kb)
            except Exception:
                return await q.message.reply_text(start_txt, reply_markup=kb)

    if action == "add_mon_prompt":
        return await q.message.reply_text("🔍 أرسل اليوزر أو الرابط للحساب ليتم مراقبته:")
    if action == "main_search":
        return await q.message.reply_text(i18n.get_msg(user_lang, "prompt_search"))
    if action == "main_dl":
        return await q.message.reply_text(i18n.get_msg(user_lang, "prompt_dl"))
    if action in ("main_mon", "main_monitors"):
        return await my_monitors(update, context)
    if action == "main_agency":
        return await agency_panel(update, context)
    if action == "main_vip":
        return await show_vip(update, context)
    if action == "main_invite":
        return await show_invite(update, context)
    if action == "main_support":
        return await support_cmd(update, context)
    if action == "main_notice":
        return await show_notice(update, context)

    if action == "dl_audio":
        # We need to answer the query immediately to show progress
        await q.answer("⏳ جاري تحميل الأغنية كملف MP3...")
        entry = await db.audio_cache.find_one({"video_id": arg})
        if not entry or not entry.get("music_url"):
            return await q.message.reply_text("❌ تعذّر العثور على رابط الأغنية.")
        url = entry["music_url"]
        b = await _download_bytes(url)
        if not b:
            return await q.message.reply_text("❌ فشل تنزيل ملف الأغنية. يرجى المحاولة لاحقاً.")
        title = entry.get("title") or "TikTok Audio"
        title = title[:45] + "..." if len(title) > 45 else title
        try:
            await context.bot.send_audio(
                chat_id=tid,
                audio=b,
                filename=f"audio_{arg}.mp3",
                title=title,
                performer="TikTok",
            )
        except Exception as e:
            log.warning("Failed to send audio file: %s", e)
            await q.message.reply_text("❌ تعذّر إرسال ملف الأغنية كملف صوتي.")
    if action == "val_calc":
        await q.answer()
        return await show_valuation(q, arg)

    if action == "open":
        p = await tk.fetch_profile(arg)
        if not p:
            return await q.message.reply_text("❌ تعذّر جلب الحساب.")
        await store_snapshot(p)
        return await context.bot.send_message(
            tid, F.profile_card(p), parse_mode=ParseMode.HTML,
            reply_markup=account_kb(p["uniqueId"]), disable_web_page_preview=True,
        )

    if action == "checksub":
        if await ensure_subscribed(update, context):
            try:
                await q.message.delete()
            except Exception:
                pass
            txt = (
                "✅ <b>تم التحقق بنجاح! تم تفعيل ميزات البوت مجاناً.</b>\n\n"
                "🎵 <b>أهلاً بك في بوت معلومات تيك توك</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "أرسل <b>اسم مستخدم</b> أو <b>رابط حساب</b> تيك توك، وأعطيك <tg-emoji emoji-id=\"5014902839575577394\">🆔</tg-emoji> بطاقة معلومات كاملة.\n\n"
                "<tg-emoji emoji-id=\"5217871625206132326\">🔎</tg-emoji> مثال: <code>@tiktok</code>\n"
                "<tg-emoji emoji-id=\"5254008401997869778\">🎬</tg-emoji> أرسل رابط فيديو لتحميله بدون علامة مائية.\n\n"
            )
            return await context.bot.send_message(
                chat_id=tid, text=txt, parse_mode=ParseMode.HTML, reply_markup=MAIN_KB
            )
        return

    if action == "adm":
        if not is_admin(tid):
            return await q.message.reply_text("🔐 غير مصرّح. أرسل «صويري» للدخول.")
        if arg == "home":
            return await q.message.reply_text(await admin_stats_text(), parse_mode=ParseMode.HTML, reply_markup=admin_kb())
        if arg == "stats":
            return await q.message.reply_text(await admin_stats_text(), parse_mode=ParseMode.HTML, reply_markup=admin_kb())
        if arg == "broadcast":
            context.user_data["await"] = "broadcast"
            return await q.message.reply_text("📢 أرسل نص الإذاعة الآن (سيُرسل لكل المستخدمين):")
        if arg == "grant":
            context.user_data["await"] = "grant"
            return await q.message.reply_text("🎁 أرسل: <code>الآيدي عدد_الأيام</code> (أو <code>الآيدي life</code>):", parse_mode=ParseMode.HTML)
        if arg == "vip":
            vips = await db.users.find({"is_vip": True}).to_list(1000)
            lines = [f"⭐ <b>مشتركو VIP:</b> {len(vips)}", "━━━━━━━━━━"]
            for u in vips[:50]:
                until = u.get("vip_until") or "دائم"
                lines.append(f"• <code>{u['telegram_id']}</code> — {until[:10] if until != 'دائم' else 'دائم'}")
            return await q.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=admin_kb())
        if arg == "forced":
            s = await get_settings()
            chans = s.get("forced_channels") or []
            kb = [[InlineKeyboardButton(f"🗑 {c}", callback_data=f"adm:rmch:{c}")] for c in chans]
            kb.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="adm:addch")])
            kb.append([InlineKeyboardButton("⬅️ رجوع", callback_data="adm:home")])
            body = "🔒 <b>الاشتراك الإجباري</b>\n" + ("\n".join(f"• {c}" for c in chans) if chans else "لا توجد قنوات مضافة.")
            return await q.message.reply_text(body, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        if arg == "addch":
            context.user_data["await"] = "add_channel"
            return await q.message.reply_text("➕ أرسل يوزر القناة (مثال: <code>@mychannel</code>):", parse_mode=ParseMode.HTML)
        if arg.startswith("rmch:"):
            ch = arg.split("rmch:", 1)[1]
            s = await get_settings()
            chans = [c for c in (s.get("forced_channels") or []) if c != ch]
            await db.settings.update_one({"_id": "settings"}, {"$set": {"forced_channels": chans}}, upsert=True)
            return await q.message.reply_text(f"🗑 حُذفت {ch}.", reply_markup=admin_kb())
        return

    if action in ("img", "level", "er", "growth", "monitor", "compare", "refresh", "pdf", "imp", "story", "high"):
        if action == "story":
            return await send_stories(q, context, arg)
        if action == "high":
            return await send_highlights(q, context, arg)
        if action == "compare":
            context.user_data["await"] = "compare"
            context.user_data["compare_a"] = arg
            return await q.message.reply_text(f"⚖️ أرسل اسم الحساب الثاني لمقارنته مع @{arg}:")

        if action == "monitor":
            return await add_monitor(q, tid, arg)

        if action == "growth":
            return await show_growth(q, arg)

        if action == "pdf":
            return await send_pdf_report(q, context, arg)

        if action == "imp":
            return await impersonation_scan(q, context, arg)

        # img / level / er / refresh need a fresh profile
        p = await tk.fetch_profile(arg)
        if not p:
            return await q.message.reply_text("❌ تعذّر جلب الحساب.")
        if action == "img":
            try:
                await context.bot.send_photo(tid, photo=p["avatar"], caption=f"🖼 صورة @{arg} بالجودة الأصلية")
            except Exception:
                await q.message.reply_text(f"🖼 رابط الصورة:\n{p['avatar']}")
        elif action == "level":
            await q.message.reply_text(F.level_card(p), parse_mode=ParseMode.HTML)
        elif action == "er":
            await q.message.reply_text(F.engagement_card(p), parse_mode=ParseMode.HTML)
        elif action == "refresh":
            await store_snapshot(p, force=True)
            try:
                await q.edit_message_text(
                    F.profile_card(p), parse_mode=ParseMode.HTML,
                    reply_markup=account_kb(arg), disable_web_page_preview=True,
                )
            except Exception:
                pass
        return

    if action == "unmon":
        await db.monitors.delete_one({"telegram_id": tid, "uniqueId": arg})
        return await q.edit_message_text(f"🗑 تم إيقاف مراقبة @{arg}.")

    if action == "impmon":
        p = await tk.fetch_profile(arg)
        if not p:
            return await q.message.reply_text("❌ تعذّر جلب الحساب.")
        exists = await db.brands.find_one({"telegram_id": tid, "uniqueId": arg})
        if exists:
            return await q.message.reply_text(f"🛡 @{arg} مسجّل بالفعل لتنبيه الانتحال.")
        await db.brands.insert_one({
            "telegram_id": tid,
            "uniqueId": arg,
            "nickname": p.get("nickname"),
            "known": [],
            "created_at": now().isoformat(),
        })
        return await q.message.reply_text(
            f"🛡 فعّلت تنبيه الانتحال لحساب @{arg}.\nسأنبّهك فوراً لو ظهر حساب يقلّد اسمك أو علامتك."
        )

    if action == "unimp":
        await db.brands.delete_one({"telegram_id": tid, "uniqueId": arg})
        return await q.edit_message_text(f"🛡 أوقفت تنبيه الانتحال لـ @{arg}.")


async def _vip_gate(q):
    await q.message.reply_text("🔒 هذه الميزة متاحة للجميع مجاناً!")


async def add_monitor(q, tid, uid):
    exists = await db.monitors.find_one({"telegram_id": tid, "uniqueId": uid})
    if exists:
        return await q.message.reply_text(f"🔔 @{uid} مراقب بالفعل.")
    p = await tk.fetch_profile(uid)
    if not p:
        return await q.message.reply_text("❌ تعذّر جلب الحساب.")
    await db.monitors.insert_one({
        "telegram_id": tid,
        "uniqueId": uid,
        "created_at": now().isoformat(),
        "last": _track(p),
    })
    await q.message.reply_text(
        f"🔔 بدأت مراقبة @{uid}.\n"
        "سأنبّهك فوراً عند: ستوري جديدة، نشر/حذف فيديو، تغيير الاسم/اليوزر/البايو/الصورة، "
        "تغيّر المتابعين، أو تحويل الحساب لخاص/عام. (فحص كل ~3 دقائق)"
    )


def _akey(url):
    """Most stable avatar identity: the image hash segment only.
    (TikTok rotates CDN host p16/p19/alisg, signature query, and size suffix.)"""
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        seg = urlparse(url).path.rstrip("/").split("/")[-1]
        return seg.split("~")[0].split(".")[0] or seg
    except Exception:
        return url


def _track(p: dict) -> dict:
    """Fields watched for changes on monitored accounts."""
    return {
        "followerCount": p.get("followerCount"),
        "followingCount": p.get("followingCount"),
        "heartCount": p.get("heartCount"),
        "videoCount": p.get("videoCount"),
        "nickname": p.get("nickname"),
        "uniqueId": p.get("uniqueId"),
        "signature": p.get("signature"),
        "avatar": _akey(p.get("avatar")),
        "privateAccount": p.get("privateAccount"),
        "verified": p.get("verified"),
        "storyStatus": p.get("storyStatus"),
    }


async def show_growth(q, uid):
    snaps = await db.snapshots.find({"uniqueId": uid}).sort("ts", 1).to_list(500)
    if len(snaps) < 2:
        return await q.message.reply_text(
            f"📈 لا توجد بيانات كافية لنمو @{uid} بعد.\nراقب الحساب وسأجمع بياناته تلقائياً 👑"
        )
    first, last = snaps[0], snaps[-1]
    d_follow = (last.get("followerCount") or 0) - (first.get("followerCount") or 0)
    d_video = (last.get("videoCount") or 0) - (first.get("videoCount") or 0)
    t0 = datetime.fromisoformat(first["ts"]).strftime("%Y-%m-%d")
    t1 = datetime.fromisoformat(last["ts"]).strftime("%Y-%m-%d")
    sign = "📈 +" if d_follow >= 0 else "📉 "
    txt = (
        f"📈 <b>تتبّع النمو</b> @{uid}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"الفترة: {t0} ← {t1}\n"
        f"👥 المتابعون: {F.fmt_num(first.get('followerCount'))} ← {F.fmt_num(last.get('followerCount'))}\n"
        f"{sign}{F.fmt_num(abs(d_follow))} متابع\n"
        f"🎬 الفيديوهات: {d_video:+d}\n"
        f"📊 عدد اللقطات المسجّلة: {len(snaps)}"
    )
    chart = await asyncio.to_thread(R.build_growth_chart, snaps, uid)
    if chart:
        try:
            with open(chart, "rb") as f:
                await q.message.reply_photo(photo=f, caption=txt, parse_mode=ParseMode.HTML)
            return
        except Exception:
            pass
    await q.message.reply_text(txt, parse_mode=ParseMode.HTML)


# ------------------------- Valuation -------------------------
async def show_valuation(q, uid: str):
    wait = await q.message.reply_text("⏳ جاري تحليل بيانات الحساب وحساب القيمة التسويقية...")
    p = await tk.fetch_profile(uid)
    try:
        await wait.delete()
    except Exception:
        pass
    if not p:
        return await q.message.reply_text("❌ تعذّر جلب بيانات الحساب.")

    followers = int(p.get("followerCount") or 0)
    hearts = int(p.get("heartCount") or 0)
    videos = int(p.get("videoCount") or 0)

    # Calculate Engagement Rate (ER)
    avg_likes = hearts / max(1, videos)
    er = (avg_likes / max(1, followers)) * 100 if followers > 0 else 0

    # ER Modifier (تأثير التفاعل على السعر)
    if er < 1.5:
        er_mod = 0.55
        er_desc = "منخفض جداً (يقلل القيمة)"
    elif er < 3.0:
        er_mod = 0.85
        er_desc = "متوسط (طبيعي)"
    elif er < 6.0:
        er_mod = 1.15
        er_desc = "جيد (يرفع القيمة)"
    elif er < 12.0:
        er_mod = 1.45
        er_desc = "ممتاز جداً (يرفع القيمة بقوة)"
    else:
        er_mod = 1.85
        er_desc = "تفاعل فيروسي خارق! 🔥 (مضاعفة القيمة)"

    # Account Equity Value (سعر شراء/بيع الحساب بالكامل)
    # Industry standard baseline: $0.0035 per follower + $0.0004 per heart, adjusted by ER
    base_val = (followers * 0.0035) + (hearts * 0.0004)
    est_val = base_val * er_mod

    # Ensure reasonable minimums for very small accounts
    if followers < 1000:
        min_acc = 5
        max_acc = 20
    else:
        min_acc = int(est_val * 0.85)
        max_acc = int(est_val * 1.15)

    # Sponsored Post Rate (سعر المنشور الإعلاني للعلامات التجارية)
    # Standard formula based on views (views approx 4x likes on average) and followers
    val_post = (followers * 0.006) + (avg_likes * 0.12)
    val_post = val_post * er_mod

    # Constrain sponsored rates to realistic industry tiers
    if followers < 5000:
        min_post = max(5, int(val_post * 0.8))
        max_post = max(10, int(val_post * 1.2))
        if min_post > 50:
            min_post, max_post = 10, 40
    elif followers < 25000:
        min_post = max(25, int(val_post * 0.85))
        max_post = max(50, int(val_post * 1.15))
        if min_post > 150:
            min_post, max_post = 40, 120
    elif followers < 100000:
        min_post = max(100, int(val_post * 0.85))
        max_post = max(200, int(val_post * 1.15))
        if min_post > 600:
            min_post, max_post = 150, 450
    elif followers < 500000:
        min_post = max(500, int(val_post * 0.9))
        max_post = max(1000, int(val_post * 1.1))
        if min_post > 2500:
            min_post, max_post = 600, 1800
    else:
        min_post = int(val_post * 0.9)
        max_post = int(val_post * 1.1)

    # Account Authority Score (قوة التأثير)
    import math
    followers_log = math.log10(max(10, followers))
    score = int(er * 8 + (followers_log * 8))
    score = min(99, max(10, score))

    if score >= 80:
        quality = "أسطوري 🔥"
    elif score >= 60:
        quality = "ممتاز ✅"
    elif score >= 40:
        quality = "متوسط 🙂"
    else:
        quality = "ضعيف ⚠️"

    txt = (
        f"💰 <b>التقييم المالي والتسويقي للحساب</b> @{F.esc(uid)}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💸 <b>القيمة التقديرية للحساب:</b>\n"
        f"← <code>${min_acc:,} - ${max_acc:,}</code>\n"
        f"<i>(سعر بيع/شراء الحساب بالكامل ملكية مطلقة)</i>\n\n"
        f"📢 <b>سعر المنشور الإعلاني المقترح:</b>\n"
        f"← <code>${min_post:,} - ${max_post:,}</code>\n"
        f"<i>(سعر الفيديو المروج أو رعاية العلامة التجارية)</i>\n\n"
        f"⭐ <b>قوة تأثير الحساب:</b>\n"
        f"← <code>{score}/100</code> ({quality})\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>تحليل الأسباب والبيانات المعتمدة:</b>\n\n"
        f"• <b>حجم الجمهور ({F.fmt_num(followers)} follower):</b> "
        f"يمنح الحساب وصولاً أساسياً وقاعدة انتشار أولية.\n"
        f"• <b>جودة التفاعل ({er:.2f}% ER):</b> "
        f"تعد نسبة التفاعل هذه <b>{er_desc}</b>. التفاعل المرتفع هو العامل الأقوى لرفع قيمة الحساب لدى الشركات لأن المشاهدات تكون حقيقية ومتحفزة.\n"
        f"• <b>متوسط الإعجابات ({F.fmt_num(int(avg_likes))} إعجاب/فيديو):</b> "
        f"يعكس شعبية المحتوى المنشور وثبات المشاهدات الفردية.\n\n"
        "💡 <i>ملاحظة: هذا التقييم مبني على أسعار السوق العالمية القياسية للرعاية (CPM $12-$18). قد تتضاعف هذه القيمة إذا كان الحساب متخصصاً بمجال ذي قيمة عالية (مثل المال والأعمال، التقنية، أو العقارات) أو تنخفض إذا كان المحتوى عشوائياً.</i>"
    )

    await q.message.reply_text(txt, parse_mode=ParseMode.HTML)


# ------------------------- PDF report -------------------------
async def send_pdf_report(q, context, uid):
    await q.message.reply_text("📄 جاري إنشاء التقرير الاحترافي...")
    p = await tk.fetch_profile(uid)
    if not p:
        return await q.message.reply_text("❌ تعذّر جلب الحساب.")
    png, pdf = None, None
    try:
        png, pdf = await asyncio.to_thread(R.build_report, p)
        with open(pdf, "rb") as f:
            await context.bot.send_document(
                q.from_user.id, document=f, filename=f"tiktok_report_{uid}.pdf",
                caption=f"📄 تقرير احترافي لحساب @{uid}",
                parse_mode=ParseMode.HTML,
            )
    except Exception as e:
        log.warning("pdf/send failed: %s", e)
        await q.message.reply_text("❌ تعذّر إنشاء أو إرسال التقرير.")
    finally:
        try:
            if png and os.path.exists(png):
                os.remove(png)
            if pdf and os.path.exists(pdf):
                os.remove(pdf)
        except Exception:
            pass


# ------------------------- stories & highlights -------------------------
async def send_stories(q, context, uid):
    tid = q.from_user.id
    await q.message.reply_text(f"📸 جاري البحث عن ستوري @{uid}...")
    stories = await tk.fetch_stories(uid)
    if not stories:
        return await q.message.reply_text("🚫 لا يوجد ستوري متاح لهذا الحساب حالياً.")
    for s in stories:
        await _send_media(context, tid, uid, s, "story")


async def send_highlights(q, context, uid):
    tid = q.from_user.id
    await q.message.reply_text(f"⭐ جاري جلب أبرز القصص لحساب @{uid}...")
    posts = await tk.fetch_posts(uid, 12)
    if not posts:
        return await q.message.reply_text("🚫 لا توجد أبرز قصص/مقاطع متاحة لهذا الحساب.")
    top = sorted(posts, key=lambda x: x.get("play_count") or 0, reverse=True)[:5]
    await q.message.reply_text(f"⭐ أبرز {len(top)} مقاطع في @{uid}:")
    for pp in top:
        media = pp
        if not media.get("play") and not media.get("images"):
            dl = await tk.download_video(f"https://www.tiktok.com/@{uid}/video/{pp['id']}")
            if dl:
                media = tk._pick_media(dl)
        await _send_media(context, tid, uid, media, "high")


# ------------------------- impersonation -------------------------
def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


async def _find_impersonators(uid: str, nickname: str) -> list[dict]:
    real_u, real_n = _norm(uid), _norm(nickname)
    seen, results = set(), []
    for kw in {nickname, uid}:
        if not kw:
            continue
        for c in await tk.search_users(kw, count=25):
            cu = c.get("uniqueId", "")
            if not cu or cu.lower() == uid.lower() or cu in seen:
                continue
            nu, nn = _norm(cu), _norm(c.get("nickname", ""))
            name_sim = difflib.SequenceMatcher(None, real_n, nn).ratio() if real_n else 0
            user_sim = difflib.SequenceMatcher(None, real_u, nu).ratio() if real_u else 0
            if (real_n and (nn == real_n or name_sim >= 0.8)) or (real_u and (real_u in nu or user_sim >= 0.85)):
                seen.add(cu)
                results.append(c)
    results.sort(key=lambda x: x.get("followerCount", 0), reverse=True)
    return results[:15]


async def impersonation_scan(q, context, uid):
    await q.message.reply_text(f"🛡 جاري فحص المقلّدين لحساب @{uid}...")
    p = await tk.fetch_profile(uid)
    if not p:
        return await q.message.reply_text("❌ تعذّر جلب الحساب.")
    sus = await _find_impersonators(uid, p.get("nickname", ""))
    if not sus:
        return await q.message.reply_text(
            f"✅ ما لقيت حسابات مشبوهة تقلّد @{uid} حالياً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛡 تفعيل تنبيه تلقائي", callback_data=f"impmon:{uid}")]]),
        )
    lines = [f"🛡 <b>حسابات محتملة تقلّد @{uid}</b>\n━━━━━━━━━━"]
    for s in sus:
        v = "✔️" if s.get("verified") else ""
        lines.append(f"• @{F.esc(s['uniqueId'])} {v} — {F.esc(s.get('nickname'))} ({F.fmt_num(s.get('followerCount')).split(' ')[0]} متابع)")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔔 تفعيل تنبيه تلقائي للانتحال", callback_data=f"impmon:{uid}")]])
    await q.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=kb)


# ------------------------- invite / referral -------------------------
async def show_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    u = await get_user(tid)
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{tid}"
    invites = u.get("invites", 0)
    rem = 20 - (invites % 20)
    txt = (
        "🎁 <b>دعوة الأصدقاء ومشاركة البوت</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎉 <b>البوت مجاني 100% لجميع المستخدمين بلا حدود وبدون أي اشتراك مدفوع!</b>\n\n"
        "شارك البوت مع أصدقائك ليستفيدوا من جميع الميزات (البحث عن الحسابات، تحميل الفيديوهات والصور بدون علامة مائية، المراقبة اللحظية، والتقارير الاحترافية):\n\n"
        f"📊 عدد الأشخاص الذين دعوتهم: <b>{invites}</b>\n\n"
        "👇 <b>رابط الدعوة الخاص بك:</b>\n"
        f"<code>{link}</code>"
    )
    target = update.callback_query.message if update.callback_query else update.message
    await target.reply_text(txt, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


# ------------------------- agency dashboard -------------------------
async def agency_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    clients = await db.agency.find({"telegram_id": tid}).to_list(AGENCY_MAX)
    lines = [
        "🏢 <b>لوحة الوكالة</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"العملاء: <b>{len(clients)}/{AGENCY_MAX}</b>",
        "",
        "الأوامر:",
        "<code>/agency add @user</code> — إضافة عميل",
        "<code>/agency del @user</code> — حذف عميل",
        "<code>/agency report</code> — تقرير فوري لكل العملاء",
        "",
        "📅 يصلك تقرير أسبوعي تلقائي لكل عميل.",
    ]
    if clients:
        lines.append("\n<b>عملاؤك:</b>")
        lines += [f"• @{c['uniqueId']}" for c in clients]
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def agency_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    parts = (update.message.text or "").split()
    if len(parts) < 2:
        return await agency_panel(update, context)
    sub = parts[1].lower()
    if sub == "add" and len(parts) >= 3:
        uid = tk.clean_username(parts[2])
        count = await db.agency.count_documents({"telegram_id": tid})
        if count >= AGENCY_MAX:
            return await update.effective_message.reply_text(f"⚠️ وصلت للحد الأقصى ({AGENCY_MAX} عميل).")
        p = await tk.fetch_profile(uid)
        if not p:
            return await update.effective_message.reply_text("❌ تعذّر جلب هذا الحساب.")
        if await db.agency.find_one({"telegram_id": tid, "uniqueId": uid}):
            return await update.effective_message.reply_text(f"@{uid} مضاف بالفعل.")
        await store_snapshot(p, force=True)
        await db.agency.insert_one({"telegram_id": tid, "uniqueId": uid, "added_at": now().isoformat()})
        return await update.effective_message.reply_text(f"✅ أضفت @{uid} لعملائك.")
    if sub in ("del", "delete", "remove") and len(parts) >= 3:
        uid = tk.clean_username(parts[2])
        await db.agency.delete_one({"telegram_id": tid, "uniqueId": uid})
        return await update.effective_message.reply_text(f"🗑 حذفت @{uid}.")
    if sub == "report":
        return await _agency_report(context, tid, immediate=True)
    return await agency_panel(update, context)


async def _agency_report(context, tid, immediate=False):
    clients = await db.agency.find({"telegram_id": tid}).to_list(AGENCY_MAX)
    if not clients:
        if immediate:
            await context.bot.send_message(tid, "🏢 لا يوجد عملاء بعد. أضف عبر /agency add @user")
        return
    header = "🏢 <b>تقرير الوكالة</b> " + ("(فوري)" if immediate else "(أسبوعي)") + "\n━━━━━━━━━━━━━━━━━━\n"
    lines = []
    for c in clients:
        uid = c["uniqueId"]
        p = await tk.fetch_profile(uid)
        if not p:
            lines.append(f"• @{uid}: تعذّر الجلب")
            continue
        await store_snapshot(p)
        wk = now() - timedelta(days=7)
        old = await db.snapshots.find_one(
            {"uniqueId": uid, "ts": {"$lte": wk.isoformat()}}, sort=[("ts", -1)]
        )
        base = await db.snapshots.find_one({"uniqueId": uid}, sort=[("ts", 1)])
        ref = old or base
        delta = (p.get("followerCount") or 0) - ((ref or {}).get("followerCount") or p.get("followerCount") or 0)
        er = F.engagement(p)["er"]
        lines.append(
            f"• <b>@{uid}</b>\n   👥 {F.fmt_num(p.get('followerCount')).split(' ')[0]} "
            f"({'+' if delta>=0 else ''}{delta:,}) | 📈 {er:.1f}% | 🎬 {p.get('videoCount')}"
        )
    await context.bot.send_message(tid, header + "\n".join(lines), parse_mode=ParseMode.HTML)


# ------------------------- jobs: weekly report + impersonation -------------------------
async def weekly_report_job(context: ContextTypes.DEFAULT_TYPE):
    owners = await db.agency.distinct("telegram_id")
    for tid in owners:
        try:
            await _agency_report(context, tid, immediate=False)
        except Exception as e:
            log.warning("weekly report failed for %s: %s", tid, e)


async def impersonation_job(context: ContextTypes.DEFAULT_TYPE):
    brands = await db.brands.find({}).to_list(1000)
    for b in brands:
        uid = b["uniqueId"]
        sus = await _find_impersonators(uid, b.get("nickname", ""))
        known = set(b.get("known") or [])
        new = [s for s in sus if s["uniqueId"] not in known]
        if new:
            lines = [f"🛡 <b>تنبيه انتحال!</b> حسابات جديدة تقلّد @{uid}\n━━━━━━━━━━"]
            for s in new:
                v = "✔️" if s.get("verified") else ""
                lines.append(f"• @{F.esc(s['uniqueId'])} {v} — {F.esc(s.get('nickname'))} ({F.fmt_num(s.get('followerCount')).split(' ')[0]})")
            try:
                await context.bot.send_message(b["telegram_id"], "\n".join(lines), parse_mode=ParseMode.HTML)
            except Exception:
                pass
            known.update(s["uniqueId"] for s in sus)
            await db.brands.update_one({"_id": b["_id"]}, {"$set": {"known": list(known)}})


# ------------------------- monitoring job -------------------------
async def _download_bytes(url, limit=48 * 1024 * 1024):
    if not url or not str(url).startswith("http"):
        return None
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120", timeout=60) as cx:
            r = await cx.get(url, headers={"Referer": "https://www.tiktok.com/"})
            if r.status_code == 200 and 0 < len(r.content) <= limit:
                return r.content
    except Exception:
        pass
    
    # Fallback to httpx if curl_cffi fails (just in case)
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as cx:
            r = await cx.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.tiktok.com/"})
            if r.status_code == 200 and 0 < len(r.content) <= limit:
                return r.content
    except Exception:
        pass
    return None


async def _send_media(context, chat_id, uid, m, kind):
    """Download and send a story/post as actual video/photos (never raw links)."""
    label = {"story": "📸 ستوري", "high": "⭐ مقطع مميّز"}.get(kind, "🎬 منشور جديد")
    parts = [f"{label} من @{F.esc(uid)}"]
    if m.get("title"):
        parts.append(F.esc(m["title"]))
    if m.get("create_time"):
        parts.append(f"📅 {F.fmt_ts(m['create_time'])}")
    if m.get("play_count") is not None:
        parts.append(
            f"<tg-emoji emoji-id=\"6037397706505195857\">👁</tg-emoji> {F.fmt_num(m.get('play_count')).split(' ')[0]}  "
            f"<tg-emoji emoji-id=\"5920332441502883031\">❤️</tg-emoji> {F.fmt_num(m.get('digg_count')).split(' ')[0]}  "
            f"💬 {F.fmt_num(m.get('comment_count')).split(' ')[0]}"
        )
    cap = "\n".join(lines)
    kb = None
    if isinstance(m.get("music"), str) and m["music"].startswith("http") and m.get("id"):
        await cache_audio(str(m["id"]), m["music"], title=(m.get("title") or "TikTok Audio"))
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎵 تنزيل الأغنية (MP3)", callback_data=f"dl_audio:{m['id']}")]])
    try:
        imgs = m.get("images") or []
        if len(imgs) == 1:
            u = imgs[0]
            try:
                await context.bot.send_photo(chat_id, photo=u, caption=cap, parse_mode=ParseMode.HTML, reply_markup=kb)
                return
            except Exception:
                b = await _download_bytes(u)
                if b:
                    await context.bot.send_photo(chat_id, photo=b, caption=cap, parse_mode=ParseMode.HTML, reply_markup=kb)
                    return
        elif len(imgs) > 1:
            media = []
            for i, u in enumerate(imgs[:10]):
                b = await _download_bytes(u)
                item_media = b if b else u
                if i == 0:
                    media.append(InputMediaPhoto(media=item_media, caption=cap, parse_mode=ParseMode.HTML))
                else:
                    media.append(InputMediaPhoto(media=item_media))
            try:
                await context.bot.send_media_group(chat_id, media=media)
                if kb:
                    await context.bot.send_message(chat_id, "📊 أدوات المنشور:", reply_markup=kb)
                return
            except Exception as e:
                log.warning("send_media_group failed: %s", e)

        play_url = m.get("play")
        if play_url and not str(play_url).endswith(".mp3"):
            try:
                await context.bot.send_video(
                    chat_id, video=play_url, caption=cap,
                    parse_mode=ParseMode.HTML, reply_markup=kb,
                )
                return
            except Exception:
                b = await _download_bytes(play_url)
                if b:
                    await context.bot.send_video(
                        chat_id, video=b, caption=cap,
                        parse_mode=ParseMode.HTML, reply_markup=kb,
                    )
                    return

        if m.get("cover"):
            try:
                await context.bot.send_photo(
                    chat_id, photo=m["cover"], caption=cap,
                    parse_mode=ParseMode.HTML, reply_markup=kb,
                )
                return
            except Exception:
                b = await _download_bytes(m["cover"])
                if b:
                    await context.bot.send_photo(
                        chat_id, photo=b, caption=cap,
                        parse_mode=ParseMode.HTML, reply_markup=kb,
                    )
                    return

        await context.bot.send_message(chat_id, cap, parse_mode=ParseMode.HTML)
    except Exception as e:
        log.warning("send media failed: %s", e)
        try:
            await context.bot.send_message(chat_id, cap + "\n⚠️ تعذّر إرسال الوسائط.", parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def _process_single_monitor(context: ContextTypes.DEFAULT_TYPE, m: dict):
    uid = m.get("uniqueId") or m.get("unique_id")
    if not uid:
        return
    p = await tk.fetch_profile(uid)
    if not p:
        return
    await store_snapshot(p)
    last = m.get("last") or {}
    cur = _track(p)
    alerts = []

    ov, nv = last.get("videoCount") or 0, cur.get("videoCount") or 0
    if nv < ov and ov:
        alerts.append(f"🗑 <b>حذف {ov-nv} فيديو.</b>")

    if last.get("nickname") and cur.get("nickname") and last["nickname"] != cur["nickname"]:
        alerts.append(f"📛 غيّر الاسم:\n{F.esc(last['nickname'])} ← {F.esc(cur['nickname'])}")
    if last.get("uniqueId") and cur.get("uniqueId") and last["uniqueId"] != cur["uniqueId"]:
        alerts.append(f"✏️ غيّر اليوزر: @{last['uniqueId']} ← @{cur['uniqueId']}")
    if "signature" in last and last.get("signature") != cur.get("signature"):
        alerts.append(f"📝 غيّر البايو:\n<i>{F.esc(cur.get('signature')) or '—'}</i>")
    if last.get("avatar") and cur.get("avatar") and _akey(last["avatar"]) != cur["avatar"]:
        alerts.append("🖼 غيّر صورة الحساب.")
    if last.get("privateAccount") is not None and last.get("privateAccount") != cur.get("privateAccount"):
        alerts.append("🔒 حوّل الحساب إلى <b>خاص</b>." if cur.get("privateAccount") else "🔓 حوّل الحساب إلى <b>عام</b>.")
    if last.get("verified") is not None and last.get("verified") != cur.get("verified"):
        alerts.append("✔️ أصبح الحساب موثّقاً." if cur.get("verified") else "❌ فقد التوثيق.")

    of, nf = last.get("followerCount") or 0, cur.get("followerCount") or 0
    if of and nf != of:
        arrow = "📈" if nf > of else "📉"
        alerts.append(f"{arrow} المتابعون: {nf-of:+,} (الآن {F.fmt_num(nf)})")
    og, ng = last.get("followingCount") or 0, cur.get("followingCount") or 0
    if og and ng != og:
        alerts.append(f"➡️ قائمة (يتابع): {ng-og:+,} (الآن {F.fmt_num(ng)})")

    if alerts:
        header = f"🔔 <b>تنبيه مراقبة</b> @{uid}\n━━━━━━━━━━\n"
        try:
            await context.bot.send_message(
                m["telegram_id"], header + "\n".join(alerts), parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            log.warning("alert send failed: %s", e)

    update = {"last": cur}
    chat = m["telegram_id"]

    # --- stories: fetch & send new ones ---
    try:
        stories = await tk.fetch_stories(uid)
        known_s = m.get("known_stories")
        if known_s is not None:
            ks = set(known_s)
            for s in stories:
                if s["id"] not in ks:
                    await _send_media(context, chat, uid, s, "story")
        update["known_stories"] = list(dict.fromkeys((known_s or []) + [s["id"] for s in stories]))[-60:]
    except Exception as e:
        log.warning("story handling failed: %s", e)

    # --- posts: fetch & send new ones (fallback to notify if source blocked) ---
    try:
        posts = await tk.fetch_posts(uid, 6)
        if posts is None:
            if nv > ov:
                await context.bot.send_message(
                    chat,
                    f"🎬 <b>@{F.esc(uid)} نشر {nv-ov} فيديو جديد!</b>\n"
                    "(تعذّر جلب المحتوى تلقائياً من هذا السيرفر — افتح الحساب لمشاهدته)",
                    parse_mode=ParseMode.HTML,
                )
        else:
            known_v = m.get("known_videos")
            if known_v is not None:
                kv = set(known_v)
                for pp in reversed(posts):  # oldest first
                    if pp["id"] not in kv:
                        media = pp
                        if not media.get("play") and not media.get("images"):
                            dl = await tk.download_video(f"https://www.tiktok.com/@{uid}/video/{pp['id']}")
                            if dl:
                                media = tk._pick_media(dl)
                        await _send_media(context, chat, uid, media, "post")
            update["known_videos"] = list(dict.fromkeys((known_v or []) + [pp["id"] for pp in posts]))[-80:]
    except Exception as e:
        log.warning("posts handling failed: %s", e)

    await db.monitors.update_one({"_id": m["_id"]}, {"$set": update})


async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    mons = await db.monitors.find({}).to_list(10000)
    if not mons:
        return
    sem = asyncio.Semaphore(15)  # Limit concurrency to 15 parallel requests
    
    async def worker(m):
        async with sem:
            try:
                await asyncio.wait_for(_process_single_monitor(context, m), timeout=30.0)
            except Exception as e:
                log.warning("monitor job worker error: %s", e)
                
    await asyncio.gather(*(worker(m) for m in mons))


# ------------------------- settings & forced subscription -------------------------
def is_admin(tid: int) -> bool:
    return tid == ADMIN_ID or tid == SUPPORT_ID or tid in ADMIN_SESSIONS


_settings_cache: dict = {"_id": "settings", "forced_channels": []}
_settings_cache_time: float = 0.0

async def get_settings() -> dict:
    global _settings_cache, _settings_cache_time
    import time
    t_now = time.time()
    if t_now - _settings_cache_time < 60:
        return _settings_cache
    try:
        s = await db.settings.find_one({"_id": "settings"})
        _settings_cache = s or {"_id": "settings", "forced_channels": []}
        _settings_cache_time = t_now
    except Exception:
        pass
    return _settings_cache


async def ensure_subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    tid = update.effective_user.id
    if is_admin(tid):
        return True
    s = await get_settings()
    chans = s.get("forced_channels") or []
    if not chans:
        return True
    missing = []
    for ch in chans:
        try:
            mem = await context.bot.get_chat_member(ch, tid)
            if mem.status in ("left", "kicked"):
                missing.append(ch)
        except Exception:
            missing.append(ch)
    if not missing:
        return True
    kb = [[InlineKeyboardButton(f"📢 اشترك: {ch}", url=f"https://t.me/{ch.lstrip('@')}")] for ch in missing]
    kb.append([InlineKeyboardButton("✅ تحقّقت — تابع", callback_data="checksub")])
    msg = update.effective_message
    if msg:
        try:
            await msg.reply_text(
                "<tg-emoji emoji-id=\"6163729951859148826\">🎫</tg-emoji> <b>الاشتراك إجباري</b>\nاشترك في القنوات التالية ثم اضغط «تحقّقت»:",
                parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb),
            )
        except Exception:
            pass
    return False


# ------------------------- admin panel -------------------------
def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="adm:stats"),
         InlineKeyboardButton("📢 إذاعة جماعية", callback_data="adm:broadcast")],
        [InlineKeyboardButton("🔒 الاشتراك الإجباري", callback_data="adm:forced")],
        [InlineKeyboardButton("🔄 تحديث", callback_data="adm:home")],
    ])


async def _stats_counts():
    total = await db.users.count_documents({})
    vips = await db.users.count_documents({"is_vip": True})
    mons = await db.monitors.count_documents({})
    n = now()
    since = {
        "اليوم": n - timedelta(days=1),
        "الأسبوع": n - timedelta(days=7),
        "الشهر": n - timedelta(days=30),
        "السنة": n - timedelta(days=365),
    }
    period = {}
    for k, t in since.items():
        period[k] = await db.users.count_documents({"joined_at": {"$gte": t.isoformat()}})
    pays = await db.payments.find({}).to_list(100000)
    stars = sum(p.get("stars", 0) for p in pays)
    return total, vips, mons, period, stars, len(pays)


async def admin_stats_text() -> str:
    total, vips, mons, period, stars, npay = await _stats_counts()
    web_doc = await db.web_stats.find_one({"_id": "global"}) or {}
    web_visits = web_doc.get("total_visits", 0)
    web_clicks = web_doc.get("bot_clicks", 0)
    web_convs = web_doc.get("conversions", 0)
    return (
        "🛠 <b>لوحة التحكم — الإحصائيات</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👥 إجمالي المستخدمين: <b>{total}</b> (البوت مجاني بالكامل 🎉)\n"
        f"🆕 اليوم: {period['اليوم']} | الأسبوع: {period['الأسبوع']}\n"
        f"🗓 الشهر: {period['الشهر']} | السنة: {period['السنة']}\n\n"
        f"🌐 <b>إحصائيات رابط الموقع (Landing Page):</b>\n"
        f"• الزيارات الإجمالية: <b>{web_visits}</b> زائر\n"
        f"• نقرات زر التحويل: <b>{web_clicks}</b>\n"
        f"• المستخدمين الفعليين (بدء البوت): <b>{web_convs}</b>\n"
        f"🔗 الرابط: <code>https://tokspy-telegram-bot.onrender.com</code>\n\n"
        f"🔔 حسابات تحت المراقبة: {mons}"
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    target = update.callback_query.message if update.callback_query else update.message
    if not is_admin(tid):
        context.user_data["await"] = "admin_pw"
        return await target.reply_text("🔐 أدخل كلمة السر للدخول للوحة التحكم:")
    await target.reply_text(await admin_stats_text(), parse_mode=ParseMode.HTML, reply_markup=admin_kb())


async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["await"] = "admin_pw"
    await update.effective_message.reply_text("🔐 أدخل كلمة السر للدخول للوحة التحكم:")


async def _broadcast_worker(bot, admin_chat_id: int, status_msg_id: int, source_chat_id: int, source_msg_id: int, text_fallback: str):
    import time
    users = await db.users.find({}, {"telegram_id": 1}).to_list(100000)
    total = len(users)
    sent = 0
    blocked = 0
    last_update = time.time()

    for i, u in enumerate(users):
        t_user = u.get("telegram_id")
        if not t_user:
            continue
        try:
            if source_chat_id and source_msg_id:
                await bot.copy_message(chat_id=t_user, from_chat_id=source_chat_id, message_id=source_msg_id)
            else:
                await bot.send_message(chat_id=t_user, text=text_fallback, parse_mode=ParseMode.HTML)
            sent += 1
            await asyncio.sleep(0.04)  # ~25 msg/sec to prevent hitting Telegram rate limits
        except RetryAfter as e:
            log.warning("Broadcast FloodControl hit, waiting %s seconds", e.retry_after)
            await asyncio.sleep(e.retry_after + 0.5)
            try:
                if source_chat_id and source_msg_id:
                    await bot.copy_message(chat_id=t_user, from_chat_id=source_chat_id, message_id=source_msg_id)
                else:
                    await bot.send_message(chat_id=t_user, text=text_fallback, parse_mode=ParseMode.HTML)
                sent += 1
            except Exception:
                blocked += 1
        except Exception:
            blocked += 1

        if (i + 1) % 250 == 0 or (time.time() - last_update > 6):
            last_update = time.time()
            try:
                pct = int(((i + 1) / total) * 100) if total else 0
                await bot.edit_message_text(
                    chat_id=admin_chat_id,
                    message_id=status_msg_id,
                    text=(
                        f"⏳ <b>جاري إرسال الإذاعة الجماعية...</b>\n\n"
                        f"📊 التقدّم: <b>{sent} / {total}</b> مستخدم\n"
                        f"🚫 المحظورين/الملغيين: {blocked}\n"
                        f"⏱ نسبة الإنجاز: {pct}%"
                    ),
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

    try:
        await bot.edit_message_text(
            chat_id=admin_chat_id,
            message_id=status_msg_id,
            text=(
                f"✅ <b>اكتملت الإذاعة الجماعية بنجاح!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👥 إجمالي المستهدفين: <b>{total}</b> مستخدم\n"
                f"📤 تم التسليم بنجاح: <b>{sent}</b> مستخدم\n"
                f"🚫 حسابات محظورة/ملغية: <b>{blocked}</b>"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=admin_kb()
        )
    except Exception:
        try:
            await bot.send_message(
                chat_id=admin_chat_id,
                text=f"✅ اكتملت الإذاعة الجماعية بنجاح!\n\nتم الإرسال إلى {sent} من أصل {total} مستخدم.",
                reply_markup=admin_kb()
            )
        except Exception:
            pass


async def _do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    tid = update.effective_user.id
    source_chat_id = update.effective_chat.id
    source_msg_id = msg.message_id
    text_fallback = (msg.text or msg.caption or "").strip()

    status_msg = await msg.reply_text(
        "🚀 <b>جاري بدء الإذاعة الجماعية...</b>\nيرجى الانتظار، سيتم إشعارك بالتقدّم مباشرة.",
        parse_mode=ParseMode.HTML
    )

    asyncio.create_task(
        _broadcast_worker(context.bot, tid, status_msg.message_id, source_chat_id, source_msg_id, text_fallback)
    )


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    if not is_admin(tid):
        return
    ADMIN_SESSIONS.add(tid)
    context.user_data["await"] = "broadcast"
    await update.effective_message.reply_text(
        "📢 <b>قسم الإذاعة الجماعية</b>\n\n"
        "أرسل الآن الرسالة (نص، صورة، فيديو، أو رسالة محولة) التي تريد إذاعتها لكل مستخدمي البوت:",
        parse_mode=ParseMode.HTML
    )


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tid = update.effective_user.id
    if not is_admin(tid):
        return
    ADMIN_SESSIONS.add(tid)
    await admin_panel(update, context)


async def _add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, ch: str):
    ch = ch.strip()
    if ch.startswith("https://t.me/"):
        ch = "@" + ch.split("t.me/")[1].strip("/")
    if not ch.startswith("@"):
        ch = "@" + ch
    s = await get_settings()
    chans = s.get("forced_channels") or []
    if ch not in chans:
        chans.append(ch)
    await db.settings.update_one({"_id": "settings"}, {"$set": {"forced_channels": chans}}, upsert=True)
    await update.effective_message.reply_text(
        f"✅ أُضيفت القناة {ch}.\n⚠️ تأكّد أن البوت <b>أدمن</b> في القناة ليتحقق من الاشتراك.",
        parse_mode=ParseMode.HTML, reply_markup=admin_kb(),
    )


async def _do_grant(update: Update, context: ContextTypes.DEFAULT_TYPE, txt: str):
    parts = txt.split()
    if len(parts) < 2:
        return await update.effective_message.reply_text("الصيغة: <code>الآيدي عدد_الأيام</code> أو <code>الآيدي life</code>", parse_mode=ParseMode.HTML)
    try:
        target = int(parts[0])
        days = None if parts[1].lower() in ("life", "دائم", "مدى") else int(parts[1])
    except ValueError:
        return await update.effective_message.reply_text("❌ صيغة غير صحيحة.")
    await grant_vip(target, days)
    await update.effective_message.reply_text(f"✅ مُنح VIP للمستخدم {target}.", reply_markup=admin_kb())


# ------------------------- main -------------------------
async def _preload_known_users():
    """Load existing users into in-memory set to prevent database queries during /start."""
    try:
        count = 0
        async for doc in db.users.find({}, {"telegram_id": 1}):
            tid = doc.get("telegram_id")
            if tid:
                KNOWN_USERS.add(tid)
                count += 1
        log.info("Preloaded %d known users into fast-path memory cache", count)
    except Exception as e:
        log.warning("Failed preloading users: %s", e)


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Gracefully handle Telegram FloodControl (429) and network timeouts without crashing."""
    err = context.error
    if isinstance(err, RetryAfter):
        log.warning("Telegram FloodControl: Retrying after %s seconds", err.retry_after)
        await asyncio.sleep(err.retry_after)
    elif isinstance(err, (TimedOut, NetworkError)):
        log.warning("Telegram network glitch: %s", err)
    else:
        log.error("Unhandled exception: %s", err, exc_info=err)

    if isinstance(update, Update):
        if update.callback_query:
            try:
                await update.callback_query.answer("⚠️ حدث خطأ مؤقت، يرجى إعادة المحاولة.", show_alert=False)
            except Exception:
                pass
        elif update.effective_message:
            try:
                await update.effective_message.reply_text("⚠️ حدث خطأ مؤقت أثناء معالجة الطلب، يرجى إرسال /start للمتابعة.")
            except Exception:
                pass


async def _post_init(app: Application):
    """Register multilingual Bot SEO and commands for global search ranking."""
    for lang in i18n.SUPPORTED_LANGUAGES:
        seo = i18n.BOT_SEO.get(lang, {})
        cmds = i18n.BOT_COMMANDS.get(lang, [])
        try:
            if seo.get("name"):
                await app.bot.set_my_name(name=seo["name"], language_code=lang)
        except Exception as e:
            log.warning("set_my_name failed for %s: %s", lang, e)
        try:
            if seo.get("short_description"):
                await app.bot.set_my_short_description(short_description=seo["short_description"], language_code=lang)
        except Exception as e:
            log.warning("set_my_short_description failed for %s: %s", lang, e)
        try:
            if seo.get("description"):
                await app.bot.set_my_description(description=seo["description"], language_code=lang)
        except Exception as e:
            log.warning("set_my_description failed for %s: %s", lang, e)
        try:
            if cmds:
                await app.bot.set_my_commands(commands=cmds, language_code=lang)
        except Exception as e:
            log.warning("set_my_commands failed for %s: %s", lang, e)

    # Fallback / Default SEO
    try:
        await app.bot.set_my_name(name=i18n.BOT_SEO["ar"]["name"])
        await app.bot.set_my_short_description(short_description=i18n.BOT_SEO["ar"]["short_description"])
        await app.bot.set_my_description(description=i18n.BOT_SEO["ar"]["description"])
        await app.bot.set_my_commands(commands=i18n.BOT_COMMANDS["ar"])
        log.info("Multilingual SEO and commands registered successfully.")
    except Exception as e:
        log.warning("Default SEO setup failed: %s", e)

    await _preload_known_users()


def main():
    httpx_req = HTTPXRequest(
        connection_pool_size=300,
        pool_timeout=30.0,
        connect_timeout=15.0,
        read_timeout=15.0,
        write_timeout=15.0,
    )
    app: Application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(httpx_req)
        .concurrent_updates(256)
        .post_init(_post_init)
        .build()
    )
    app.add_error_handler(global_error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("panel", admin_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("bc", broadcast_cmd))
    app.add_handler(CommandHandler("lang", lang_cmd))
    app.add_handler(CommandHandler("support", support_cmd))
    app.add_handler(CommandHandler("vip", show_vip))
    app.add_handler(CommandHandler("dev", support_cmd))
    app.add_handler(CommandHandler("invite", show_invite))
    app.add_handler(CommandHandler("agency", agency_cmd))
    app.add_handler(ChatJoinRequestHandler(on_join_request))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(~filters.COMMAND, router))

    app.job_queue.run_repeating(monitor_job, interval=180, first=20)
    app.job_queue.run_repeating(impersonation_job, interval=6 * 3600, first=300)
    app.job_queue.run_repeating(weekly_report_job, interval=7 * 24 * 3600, first=600)

    log.info("Bot starting (high-concurrency polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False, bootstrap_retries=-1)


if __name__ == "__main__":
    main()