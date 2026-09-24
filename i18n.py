"""
Internationalization (i18n) and SEO module for TokSpy Bot.
Supports: Arabic (ar), English (en), Russian (ru), Chinese (zh), Persian/Farsi (fa), Turkish (tr).
"""

from typing import Dict, Any, List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, BotCommand

SUPPORTED_LANGUAGES = ["ar", "en", "ru", "zh", "fa", "tr"]

# SEO Metadata for Telegram Global Search ranking across languages
BOT_SEO = {
    "ar": {
        "name": "بوت معلومات تيك توك TikTok information",
        "short_description": "أقوى أداة تيك توك: كشف الحسابات، تحميل بدون علامة مائية، مراقبة التفاعلات والإحصائيات.",
        "description": (
            "🔥 أهلاً بك في البوت الأقوى والأسرع في تيليجرام لخدمات تيك توك!\n\n"
            "✨ المميزات:\n"
            "🔍 كشف وتحليل بيانات حسابات تيك توك بدقة.\n"
            "📥 تحميل فيديوهات تيك توك بدون علامة مائية وبأعلى دقة.\n"
            "👁 مراقبة الحسابات ومتابعة أحدث التغييرات والإحصائيات لحظياً.\n"
            "⚡ سرعة فائقة ودعم لجميع الأجهزة."
        )
    },
    "en": {
        "name": "TokSpy - TikTok Analytics & Downloader",
        "short_description": "Analyze TikTok profiles, download HD videos without watermark & monitor accounts real-time.",
        "description": (
            "🔥 Welcome to TokSpy - the ultimate Telegram bot for TikTok analytics and tools!\n\n"
            "✨ Features:\n"
            "🔍 Deep TikTok user search, analytics, and intelligence.\n"
            "📥 Download TikTok videos in HD without watermark.\n"
            "👁 24/7 account monitoring with instant real-time alerts.\n"
            "⚡ Ultra-fast performance and seamless user experience."
        )
    },
    "ru": {
        "name": "TokSpy - Аналитика и Скачивание ТикТок",
        "short_description": "Анализ аккаунтов TikTok, скачивание видео без водяного знака и мониторинг в реальном времени.",
        "description": (
            "🔥 Добро пожаловать в TokSpy — лучший бот в Telegram для TikTok!\n\n"
            "✨ Возможности:\n"
            "🔍 Поиск, статистика и глубокий анализ профилей TikTok.\n"
            "📥 Скачивание любых видео TikTok без водяного знака в качестве HD.\n"
            "👁 Мониторинг изменений и активности аккаунтов 24/7.\n"
            "⚡ Максимальная скорость работы и удобный интерфейс."
        )
    },
    "zh": {
        "name": "TokSpy - TikTok 数据分析与无水印下载",
        "short_description": "TikTok 用户分析工具、高清无水印视频下载与全天候账号监控。",
        "description": (
            "🔥 欢迎使用 TokSpy — Telegram 上最强大的 TikTok 综合工具机器人！\n\n"
            "✨ 功能特色：\n"
            "🔍 TikTok 账号深度分析与数据监测。\n"
            "📥 高清无水印快速下载 TikTok 视频与音频。\n"
            "👁 全天候账号监控，数据变动实时提醒。\n"
            "⚡ 超高性能，极速响应。"
        )
    },
    "fa": {
        "name": "توک اسپای | ردیاب و دانلودر تیک تاک",
        "short_description": "آنالیز دقیق تیک تاک، دانلود ویدیو بدون واترمارک و مانیتورینگ زنده پیج‌ها.",
        "description": (
            "🔥 به توک‌اسپای (TokSpy) خوش آمدید — کامل‌ترین ربات تلگرام برای ابزارهای تیک‌تاک!\n\n"
            "✨ امکانات:\n"
            "🔍 تحلیل جامع و بررسی اطلاعات پیج‌های تیک‌تاک.\n"
            "📥 دانلود سریع ویدیوهای تیک‌تاک بدون واترمارک و با کیفیت اصلی.\n"
            "👁 مانیتورینگ ۲۴ ساعته حساب‌ها و اعلان تغییرات لحظه‌ای.\n"
            "⚡ سرعت فوق‌العاده و عملکرد پایدار."
        )
    },
    "tr": {
        "name": "TokSpy - TikTok Analiz ve Video İndirici",
        "short_description": "TikTok profil analizi, filigransız video indirme ve anlık hesap takibi.",
        "description": (
            "🔥 TokSpy'a hoş geldiniz — Telegram'daki en güçlü TikTok analiz ve araç botu!\n\n"
            "✨ Özellikler:\n"
            "🔍 TikTok profil sorgulama, istatistik ve detaylı analiz.\n"
            "📥 Filigransız HD kalitede TikTok video indirme.\n"
            "👁 7/24 kesintisiz hesap takip ve anlık bildirimler.\n"
            "⚡ Yüksek hızlı ve kesintisiz performans."
        )
    }
}

# Bot Commands per language
BOT_COMMANDS = {
    "ar": [
        BotCommand("start", "بدء استخدام البوت"),
        BotCommand("lang", "تغيير لغة البوت"),
        BotCommand("support", "الدعم الفني والمساعدة"),
        BotCommand("help", "معلومات وكيفية الاستخدام"),
    ],
    "en": [
        BotCommand("start", "Start the bot"),
        BotCommand("lang", "Change language"),
        BotCommand("support", "Technical Support"),
        BotCommand("help", "Help & info"),
    ],
    "ru": [
        BotCommand("start", "Запустить бота"),
        BotCommand("lang", "Сменить язык"),
        BotCommand("support", "Техподдержка"),
        BotCommand("help", "Помощь и инструкции"),
    ],
    "zh": [
        BotCommand("start", "启动机器人"),
        BotCommand("lang", "更改语言"),
        BotCommand("support", "技术支持"),
        BotCommand("help", "帮助与说明"),
    ],
    "fa": [
        BotCommand("start", "شروع ربات"),
        BotCommand("lang", "تغییر زبان"),
        BotCommand("support", "پشتیبانی فنی"),
        BotCommand("help", "راهنما و اطلاعات"),
    ],
    "tr": [
        BotCommand("start", "Botu başlat"),
        BotCommand("lang", "Dili değiştir"),
        BotCommand("support", "Teknik Destek"),
        BotCommand("help", "Yardım ve bilgi"),
    ],
}

# UI Strings
MESSAGES = {
    "ar": {
        "start_title": "مرحباً بك في TokSpy ⚡",
        "start_body": (
            "أقوى منصة لمراقبة وتحليل حسابات تيك توك وتنزيل الفيديوهات.\n\n"
            "اختر من القائمة أدناه للبدء:"
        ),
        "btn_search": "🔍 كشف حساب تيك توك",
        "btn_dl": "📥 تحميل فيديو بدون علامة",
        "btn_mon": "👁️ المراقبة والتنبيهات",
        "btn_invite": "🎁 دعوة الأصدقاء",
        "btn_support": "💬 الدعم الفني",
        "btn_lang": "🌐 اللغة (Language)",
        "prompt_search": "🔍 أرسل يوزر حساب تيك توك للبدء بالتحليل والبحث:",
        "prompt_dl": "📥 أرسل رابط فيديو تيك توك لتحميله بدون علامة مائية وبأعلى دقة:",
        "support_text": (
            "💬 <b>قسم الدعم الفني</b>\n\n"
            "إذا واجهتك أي مشكلة أو كان لديك استفسار أو اقتراح، اضغط على الزر أدناه للتواصل مباشرة مع فريق الدعم."
        ),
        "btn_contact_support": "💬 تواصل مع الدعم الفني",
        "btn_back_home": "🔙 العودة للقائمة الرئيسية",
        "lang_selected": "✅ تم ضبط اللغة إلى: العربية 🇸🇦",
        "choose_lang": "🌐 اختر لغة البوت / Select bot language:"
    },
    "en": {
        "start_title": "Welcome to TokSpy ⚡",
        "start_body": (
            "The leading platform for TikTok profile intelligence, analytics, and video downloading.\n\n"
            "Select an option below to begin:"
        ),
        "btn_search": "🔍 Inspect TikTok Profile",
        "btn_dl": "📥 Download (No Watermark)",
        "btn_mon": "👁️ Account Monitoring",
        "btn_invite": "🎁 Invite Friends",
        "btn_support": "💬 Support",
        "btn_lang": "🌐 Language",
        "prompt_search": "🔍 Send a TikTok username to inspect and analyze:",
        "prompt_dl": "📥 Send a TikTok video link to download in HD without watermark:",
        "support_text": (
            "💬 <b>Technical Support</b>\n\n"
            "If you have any issues, questions, or feedback, click the button below to reach our support team directly."
        ),
        "btn_contact_support": "💬 Contact Support",
        "btn_back_home": "🔙 Back to Main Menu",
        "lang_selected": "✅ Language set to: English 🇬🇧",
        "choose_lang": "🌐 Select bot language:"
    },
    "ru": {
        "start_title": "Добро пожаловать в TokSpy ⚡",
        "start_body": (
            "Мощная платформа для анализа профилей TikTok, скачивания видео без водяного знака и мониторинга.\n\n"
            "Выберите нужное действие ниже:"
        ),
        "btn_search": "🔍 Анализ профиля TikTok",
        "btn_dl": "📥 Скачать видео (без знака)",
        "btn_mon": "👁️ Мониторинг аккаунтов",
        "btn_invite": "🎁 Пригласить друзей",
        "btn_support": "💬 Поддержка",
        "btn_lang": "🌐 Язык (Language)",
        "prompt_search": "🔍 Отправьте юзернейм (ник) аккаунта TikTok для поиска и анализа:",
        "prompt_dl": "📥 Отправьте ссылку на видео TikTok для скачивания без водяного знака в HD:",
        "support_text": (
            "💬 <b>Служба технической поддержки</b>\n\n"
            "Если у вас возникли вопросы, проблемы или предложения, нажмите кнопку ниже для связи с поддержкой."
        ),
        "btn_contact_support": "💬 Связаться с поддержкой",
        "btn_back_home": "🔙 Главное меню",
        "lang_selected": "✅ Язык установлен: Русский 🇷🇺",
        "choose_lang": "🌐 Выберите язык / Select language:"
    },
    "zh": {
        "start_title": "欢迎使用 TokSpy ⚡",
        "start_body": (
            "领先的 TikTok 账号分析、无水印视频高速下载与数据监控平台。\n\n"
            "请选择下方功能开始体验："
        ),
        "btn_search": "🔍 TikTok 账号深度分析",
        "btn_dl": "📥 无水印高清下载",
        "btn_mon": "👁️ 账号监控与提醒",
        "btn_invite": "🎁 邀请好友",
        "btn_support": "💬 技术支持",
        "btn_lang": "🌐 语言设置 (Language)",
        "prompt_search": "🔍 请发送 TikTok 用户名开始查询与数据分析：",
        "prompt_dl": "📥 请发送 TikTok 视频链接以快速无水印下载：",
        "support_text": (
            "💬 <b>技术支持中心</b>\n\n"
            "如遇到任何问题、使用咨询或合作建议，请点击下方按钮直接联系专属客服。"
        ),
        "btn_contact_support": "💬 联系客服支持",
        "btn_back_home": "🔙 返回主菜单",
        "lang_selected": "✅ 已切换语言为：中文 🇨🇳",
        "choose_lang": "🌐 请选择语言 / Select language:"
    },
    "fa": {
        "start_title": "به توک‌اسپای خوش آمدید ⚡",
        "start_body": (
            "پیشرفته‌ترین ربات آنالیز حساب‌های تیک‌تاک، دانلود بدون واترمارک و پایش لحظه‌ای.\n\n"
            "برای شروع یکی از گزینه‌های زیر را انتخاب کنید:"
        ),
        "btn_search": "🔍 آنالیز حساب تیک‌تاک",
        "btn_dl": "📥 دانلود ویدیو بدون واترمارک",
        "btn_mon": "👁️ مانیتورینگ حساب‌ها",
        "btn_invite": "🎁 دعوت از دوستان",
        "btn_support": "💬 پشتیبانی فنی",
        "btn_lang": "🌐 تغییر زبان (Language)",
        "prompt_search": "🔍 نام کاربری (آیدی) تیک‌تاک مورد نظر را جهت آنالیز ارسال کنید:",
        "prompt_dl": "📥 لینک ویدیوی تیک‌تاک را جهت دانلود با کیفیت اصلی و بدون آرم ارسال کنید:",
        "support_text": (
            "💬 <b>بخش پشتیبانی فنی</b>\n\n"
            "در صورت بروز هرگونه مشکل یا داشتن سؤال، روی دکمه زیر کلیک کرده و با کارشناسان ما در ارتباط باشید."
        ),
        "btn_contact_support": "💬 ارتباط با پشتیبانی",
        "btn_back_home": "🔙 بازگشت به منوی اصلی",
        "lang_selected": "✅ زبان تنظیم شد بر روی: فارسی 🇮🇷",
        "choose_lang": "🌐 لطفاً زبان مورد نظر را انتخاب کنید:"
    },
    "tr": {
        "start_title": "TokSpy'a Hoş Geldiniz ⚡",
        "start_body": (
            "TikTok profil analizi, filigransız video indirme ve anlık hesap izleme platformu.\n\n"
            "Başlamak için aşağıdaki seçeneklerden birini seçin:"
        ),
        "btn_search": "🔍 TikTok Profil Analizi",
        "btn_dl": "📥 Filigransız Video İndir",
        "btn_mon": "👁️ Hesap Takibi",
        "btn_invite": "🎁 Arkadaşlarını Davet Et",
        "btn_support": "💬 Teknik Destek",
        "btn_lang": "🌐 Dil Seçimi (Language)",
        "prompt_search": "🔍 Analiz etmek istediğiniz TikTok kullanıcı adını gönderin:",
        "prompt_dl": "📥 Filigransız ve HD kalitede indirmek istediğiniz TikTok video bağlantısını gönderin:",
        "support_text": (
            "💬 <b>Teknik Destek Bölümü</b>\n\n"
            "Herhangi bir sorun, soru veya öneriniz varsa, doğrudan destek ekibimizle görüşmek için aşağıdaki butona tıklayın."
        ),
        "btn_contact_support": "💬 Destek Ekibiyle İletişime Geç",
        "btn_back_home": "🔙 Ana Menüye Dön",
        "lang_selected": "✅ Dil seçildi: Türkçe 🇹🇷",
        "choose_lang": "🌐 Lütfen bot dilini seçin / Select language:"
    }
}

LANGUAGE_NAMES = {
    "ar": "العربية 🇸🇦",
    "en": "English 🇬🇧",
    "ru": "Русский 🇷🇺",
    "zh": "中文 🇨🇳",
    "fa": "فارسی 🇮🇷",
    "tr": "Türkçe 🇹🇷"
}


def detect_lang(raw_code: str | None) -> str:
    """
    Normalizes a telegram user language_code (e.g. 'ru-RU', 'zh-CN', 'ar', 'fa_IR')
    into one of the supported codes: ['ar', 'en', 'ru', 'zh', 'fa', 'tr'].
    Defaults to 'ar' if Arabic, or 'en' for other unsupported languages.
    """
    if not raw_code:
        return "ar"
    code = raw_code.strip().lower()
    for supported in SUPPORTED_LANGUAGES:
        if code.startswith(supported):
            return supported
    return "en"


def get_msg(lang: str, key: str) -> str:
    """Retrieves localized text with fallback to English or Arabic."""
    lang_dict = MESSAGES.get(lang) or MESSAGES["en"]
    return lang_dict.get(key, MESSAGES["en"].get(key, ""))


def get_start_text(lang: str) -> str:
    title = get_msg(lang, "start_title")
    body = get_msg(lang, "start_body")
    return f"✨ <b>{title}</b>\n\n{body}"


def get_main_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Builds the main interactive keyboard in the user's language."""
    kb = [
        [
            InlineKeyboardButton(get_msg(lang, "btn_search"), callback_data="main_search"),
            InlineKeyboardButton(get_msg(lang, "btn_dl"), callback_data="main_dl"),
        ],
        [
            InlineKeyboardButton(get_msg(lang, "btn_mon"), callback_data="main_monitors"),
            InlineKeyboardButton(get_msg(lang, "btn_invite"), callback_data="main_invite"),
        ],
        [
            InlineKeyboardButton(get_msg(lang, "btn_support"), callback_data="main_support"),
            InlineKeyboardButton(get_msg(lang, "btn_lang"), callback_data="set_lang"),
        ]
    ]
    return InlineKeyboardMarkup(kb)


def get_language_selection_keyboard() -> InlineKeyboardMarkup:
    """Builds the language switcher keyboard."""
    buttons = []
    keys = list(LANGUAGE_NAMES.keys())
    for i in range(0, len(keys), 2):
        row = []
        for code in keys[i:i+2]:
            row.append(InlineKeyboardButton(LANGUAGE_NAMES[code], callback_data=f"lang:{code}"))
        buttons.append(row)
    # Add back button
    buttons.append([InlineKeyboardButton("🔙 Back / العودة", callback_data="back_home")])
    return InlineKeyboardMarkup(buttons)


def get_support_keyboard(lang: str, support_id: str = "6641619062") -> InlineKeyboardMarkup:
    """Builds the support keyboard with user-friendly direct contact."""
    btn_text = get_msg(lang, "btn_contact_support")
    back_text = get_msg(lang, "btn_back_home")
    kb = [
        [InlineKeyboardButton(btn_text, url=f"tg://user?id={support_id}")],
        [InlineKeyboardButton(back_text, callback_data="back_home")]
    ]
    return InlineKeyboardMarkup(kb)
