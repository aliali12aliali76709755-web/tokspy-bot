"""Arabic message formatting for the TikTok info bot (HTML parse mode)."""
import html
from datetime import datetime, timezone

YES = "✅ نعم"
NO = "❌ لا"

_COMMENT = {0: "الجميع", 1: "الأصدقاء", 2: "الأصدقاء", 3: "لا أحد"}
_FOLLOW_VIS = {0: "غير محدد", 1: "الجميع", 2: "الأصدقاء", 3: "أنا فقط"}
_RELATION = {0: "لا يوجد", 1: "أنت تتابعه", 2: "متابعة متبادلة"}

LEVELS = [
    (10_000_000, "🏆 أسطورة", "Legend"),
    (1_000_000, "👑 نجم كبير", "Mega Star"),
    (100_000, "💎 نجم", "Star"),
    (10_000, "🔥 مؤثّر", "Influencer"),
    (1_000, "⭐ نجم صاعد", "Rising"),
    (0, "🌱 حساب جديد", "Newbie"),
]


def esc(v) -> str:
    return html.escape(str(v)) if v is not None else ""


def fmt_num(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B ({n:,})"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M ({n:,})"
    if n >= 1_000:
        return f"{n/1_000:.1f}K ({n:,})"
    return f"{n:,}"


def fmt_ts(ts) -> str:
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return "غير متاح"
    if ts <= 0:
        return "لم يُعدّل"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def yn(v) -> str:
    return YES if v else NO


def _setting(v, table) -> str:
    if v is None:
        return "غير محدد"
    return table.get(int(v), "غير محدد") if str(v).lstrip("-").isdigit() else "غير محدد"


def account_level(followers: int):
    """Return (label, next_target, progress_ratio)."""
    followers = int(followers or 0)
    for i, (threshold, label, _en) in enumerate(LEVELS):
        if followers >= threshold:
            if i == 0:
                return label, None, 1.0
            nxt = LEVELS[i - 1][0]
            ratio = min(1.0, (followers - threshold) / (nxt - threshold)) if nxt > threshold else 1.0
            return label, nxt, ratio
    return LEVELS[-1][1], LEVELS[-2][0], 0.0


def progress_bar(ratio: float, size: int = 10) -> str:
    filled = int(round(ratio * size))
    return "▰" * filled + "▱" * (size - filled)


def engagement(p: dict) -> dict:
    followers = max(1, int(p.get("followerCount") or 0))
    videos = max(1, int(p.get("videoCount") or 0))
    hearts = int(p.get("heartCount") or 0)
    avg_likes = hearts / videos
    er = (avg_likes / followers) * 100
    return {"avg_likes": avg_likes, "er": er}


def profile_card(p: dict) -> str:
    """Full Arabic info card matching the requested layout."""
    label, _, _ = account_level(p.get("followerCount"))
    bio = esc(p.get("signature")) or "—"
    link = esc(p.get("bioLink")) if p.get("bioLink") else "لا يوجد"
    region = esc(p.get("region")) or "غير متاح"
    lang = esc(p.get("language")) or "غير متاح"
    cat = esc(p.get("category")) or "—"

    lines = [
        f"🎵 <b>معلومات حساب تيك توك</b>  {label}",
        "━━━━━━━━━━━━━━━━━━",
        f"👤 <b>اسم المستخدم:</b> @{esc(p.get('uniqueId'))}",
        f"🆔 <b>المعرف:</b> <code>{esc(p.get('id'))}</code>",
        f"📛 <b>الاسم:</b> {esc(p.get('nickname'))}",
        "",
        f"👥 <b>المتابعين:</b> {fmt_num(p.get('followerCount'))}",
        f"➡️ <b>يتابع:</b> {fmt_num(p.get('followingCount'))}",
        f"🤝 <b>الأصدقاء:</b> {fmt_num(p.get('friendCount'))}",
        f"❤️ <b>الإعجابات:</b> {fmt_num(p.get('heartCount'))}",
        f"🎬 <b>الفيديوهات:</b> {fmt_num(p.get('videoCount'))}",
        "",
        f"📅 <b>تاريخ الإنشاء:</b> {fmt_ts(p.get('createTime'))}",
        f"✏️ <b>تعديل اليوزر:</b> {fmt_ts(p.get('uniqueIdModifyTime'))}",
        f"✏️ <b>تعديل الاسم:</b> {fmt_ts(p.get('nickNameModifyTime'))}",
        f"🌍 <b>الدولة:</b> {region}",
        f"🗣 <b>اللغة:</b> {lang}",
        "",
        f"✔️ <b>حساب موثّق:</b> {yn(p.get('verified'))}",
        f"🔒 <b>حساب خاص:</b> {yn(p.get('privateAccount'))}",
        f"🕵️ <b>حساب سري:</b> {yn(p.get('secret'))}",
        f"🏢 <b>حساب منظمة:</b> {yn(p.get('isOrganization'))}",
        f"🛍 <b>يمتلك متجر:</b> {yn(p.get('commerceUser'))}  ({cat})",
        f"🛒 <b>يبيع على تيك توك:</b> {yn(p.get('ttSeller'))}",
        f"⭐ <b>المفضلة مفتوحة:</b> {yn(p.get('openFavorite'))}",
        f"🔗 <b>علاقة الحساب:</b> {_RELATION.get(int(p.get('relation') or 0), 'غير محدد')}",
        f"🚫 <b>حظر التضمين:</b> {yn(p.get('isEmbedBanned'))}",
        f"📣 <b>حساب إعلانات وهمي:</b> {yn(p.get('isADVirtual'))}",
        f"⚖️ <b>متوافق FTC:</b> {yn(p.get('ftc'))}",
        "",
        "⚙️ <b>الإعدادات والخصوصية</b>",
        f"💬 <b>التعليقات:</b> {_setting(p.get('commentSetting'), _COMMENT)}",
        f"🎭 <b>الدويتو:</b> {_setting(p.get('duetSetting'), _COMMENT)}",
        f"✂️ <b>النشر (Stitch):</b> {_setting(p.get('stitchSetting'), _COMMENT)}",
        f"👁 <b>إظهار المتابعين:</b> {_setting(p.get('followingVisibility'), _FOLLOW_VIS)}",
        f"🎵 <b>عرض الموسيقى:</b> {yn(p.get('showMusicTab'))}",
        f"❓ <b>عرض الأسئلة:</b> {yn(p.get('showQuestionTab'))}",
        f"📋 <b>عرض القوائم:</b> {yn(p.get('showPlayListTab'))}",
        f"➕ <b>توسيع القوائم:</b> {yn(p.get('canExpPlaylist'))}",
        f"🔗 <b>اقتراح ربط حساب:</b> {yn(p.get('suggestAccountBind'))}",
        "",
        f"📝 <b>البايو:</b> {bio}",
        f"🔗 <b>الرابط في البايو:</b> {link}",
    ]
    return "\n".join(lines)


def level_card(p: dict) -> str:
    label, nxt, ratio = account_level(p.get("followerCount"))
    followers = int(p.get("followerCount") or 0)
    bar = progress_bar(ratio)
    out = [
        f"🏆 <b>مستوى الحساب</b> @{esc(p.get('uniqueId'))}",
        "━━━━━━━━━━━━━━━━━━",
        f"المستوى الحالي: <b>{label}</b>",
        f"👥 المتابعون: {fmt_num(followers)}",
        f"\n{bar}  {int(ratio*100)}%",
    ]
    if nxt:
        remaining = nxt - followers
        out.append(f"\n📈 باقي <b>{fmt_num(remaining)}</b> متابع للمستوى التالي.")
    else:
        out.append("\n🎉 وصل لأعلى مستوى ممكن!")
    return "\n".join(out)


def engagement_card(p: dict) -> str:
    e = engagement(p)
    quality = "ممتاز 🔥" if e["er"] >= 10 else "جيد جداً ✅" if e["er"] >= 5 else "متوسط 🙂" if e["er"] >= 2 else "منخفض ⚠️"
    return "\n".join([
        f"📊 <b>معدل التفاعل</b> @{esc(p.get('uniqueId'))}",
        "━━━━━━━━━━━━━━━━━━",
        f"👥 المتابعون: {fmt_num(p.get('followerCount'))}",
        f"❤️ إجمالي الإعجابات: {fmt_num(p.get('heartCount'))}",
        f"🎬 عدد الفيديوهات: {fmt_num(p.get('videoCount'))}",
        "",
        f"⭐ متوسط الإعجابات لكل فيديو: <b>{fmt_num(int(e['avg_likes']))}</b>",
        f"📈 معدل التفاعل التقريبي: <b>{e['er']:.2f}%</b>",
        f"🏅 التقييم: <b>{quality}</b>",
        "",
        "<i>ملاحظة: تقدير مبني على البيانات العامة.</i>",
    ])


def compare_card(a: dict, b: dict) -> str:
    def row(icon, key_label, key, fmt=fmt_num):
        va, vb = a.get(key) or 0, b.get(key) or 0
        win_a = "🥇" if va > vb else ("" if va == vb else "  ")
        win_b = "🥇" if vb > va else ""
        return f"{icon} <b>{key_label}</b>\n    @{esc(a.get('uniqueId'))}: {fmt(va)} {win_a}\n    @{esc(b.get('uniqueId'))}: {fmt(vb)} {win_b}"

    ea, eb = engagement(a), engagement(b)
    return "\n".join([
        f"⚖️ <b>مقارنة الحسابات</b>",
        "━━━━━━━━━━━━━━━━━━",
        row("👥", "المتابعون", "followerCount"),
        row("❤️", "الإعجابات", "heartCount"),
        row("🎬", "الفيديوهات", "videoCount"),
        f"📈 <b>معدل التفاعل</b>\n    @{esc(a.get('uniqueId'))}: {ea['er']:.2f}%\n    @{esc(b.get('uniqueId'))}: {eb['er']:.2f}%",
    ])
