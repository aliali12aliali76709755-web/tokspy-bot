"""Report generation: professional PDF/PNG account report + growth chart.

Uses Pillow to render a designed report image (saved as PNG and PDF) and
matplotlib for the growth chart. Arabic text is shaped with arabic_reshaper
+ python-bidi.
"""
import io
import os
from datetime import datetime, timezone

import tempfile
import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

import formatting as F

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
FONT = os.path.join(ASSETS, "Cairo.ttf")
OUT = tempfile.gettempdir()

font_manager.fontManager.addfont(FONT)
_MPL_FONT = font_manager.FontProperties(fname=FONT)

BG_TOP = (13, 17, 30)
BG_BOT = (28, 20, 48)
ACCENT = (0, 230, 195)   # tiktok teal
PINK = (255, 60, 100)
WHITE = (245, 245, 250)
MUTED = (150, 155, 175)
CARD = (26, 30, 46)


import arabic_reshaper
from bidi.algorithm import get_display

def ar(text: str) -> str:
    if not text:
        return ""
    try:
        if any("\u0600" <= c <= "\u06ff" for c in str(text)):
            reshaped = arabic_reshaper.reshape(str(text))
            return get_display(reshaped)
    except Exception:
        pass
    return str(text)


def _font(size: int) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_axes([700])  # bold weight if variable
    except Exception:
        pass
    return f


def _gradient(w: int, h: int) -> Image.Image:
    top = np.array(BG_TOP)
    bot = np.array(BG_BOT)
    t = np.linspace(0, 1, h)[:, None]
    grad = (top[None, :] * (1 - t) + bot[None, :] * t).astype(np.uint8)
    arr = np.repeat(grad[:, None, :], w, axis=1)
    return Image.fromarray(arr, "RGB")


def _circle_avatar(url: str, size: int) -> Image.Image | None:
    try:
        r = httpx.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        im = Image.open(io.BytesIO(r.content)).convert("RGB").resize((size, size))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        out = ImageOps.fit(im, (size, size))
        out.putalpha(mask)
        return out
    except Exception:
        return None


def _center(draw, cx, y, text, font, fill):
    txt = ar(text)
    w = draw.textlength(txt, font=font)
    draw.text((cx - w / 2, y), txt, font=font, fill=fill)


def _stat_card(draw, x, y, w, h, value, label):
    draw.rounded_rectangle((x, y, x + w, y + h), radius=22, fill=CARD)
    fv = _font(40)
    fl = _font(24)
    _center(draw, x + w / 2, y + 20, value, fv, WHITE)
    _center(draw, x + w / 2, y + 78, label, fl, ACCENT)


def build_report(p: dict) -> tuple[str, str]:
    """Render report; return (png_path, pdf_path)."""
    W, H = 1080, 1350
    img = _gradient(W, H)
    d = ImageDraw.Draw(img)

    # header accent bar
    d.rounded_rectangle((0, 0, W, 8), fill=ACCENT)

    # title
    _center(d, W / 2, 40, ar("تقرير حساب تيك توك"), _font(46), WHITE)

    # avatar
    av = _circle_avatar(p.get("avatar"), 220)
    if av:
        img.paste(av, (int(W / 2 - 110), 120), av)
        d.ellipse((W / 2 - 114, 116, W / 2 + 114, 344), outline=ACCENT, width=5)

    # name + username
    _center(d, W / 2, 360, p.get("nickname", ""), _font(46), WHITE)
    badge = "  (موثّق)" if p.get("verified") else ""
    _center(d, W / 2, 420, f"@{p.get('uniqueId','')}{badge}", _font(30), ACCENT)

    # level (strip leading emoji, keep Arabic label)
    label, _, _ = F.account_level(p.get("followerCount"))
    label = label.split(" ", 1)[-1]
    _center(d, W / 2, 470, label, _font(30), PINK)

    # stat cards grid (2x2)
    cw, ch, gap = 480, 130, 40
    x0 = (W - (cw * 2 + gap)) / 2
    y0 = 540
    stats = [
        (F.fmt_num(p.get("followerCount")).split(" ")[0], "المتابعون"),
        (F.fmt_num(p.get("heartCount")).split(" ")[0], "الإعجابات"),
        (F.fmt_num(p.get("videoCount")).split(" ")[0], "الفيديوهات"),
        (F.fmt_num(p.get("followingCount")).split(" ")[0], "يتابع"),
    ]
    for i, (v, l) in enumerate(stats):
        cx = x0 + (i % 2) * (cw + gap)
        cy = y0 + (i // 2) * (ch + gap)
        _stat_card(d, cx, cy, cw, ch, v, l)

    # engagement bar
    e = F.engagement(p)
    ey = y0 + 2 * (ch + gap) + 20
    d.rounded_rectangle((x0, ey, x0 + cw * 2 + gap, ey + 150), radius=22, fill=CARD)
    _center(d, W / 2, ey + 20, ar("معدل التفاعل التقريبي"), _font(28), MUTED)
    _center(d, W / 2, ey + 60, f"{e['er']:.2f}%", _font(56), ACCENT)
    _center(d, W / 2, ey + 130, ar(f"متوسط {F.fmt_num(int(e['avg_likes'])).split(' ')[0]} إعجاب/فيديو"), _font(22), MUTED)

    # footer
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d.rounded_rectangle((0, H - 70, W, H), fill=(10, 12, 22))
    _center(d, W / 2, H - 55, ar(date), _font(26), MUTED)

    uid = p.get("uniqueId", "account")
    png = os.path.join(OUT, f"report_{uid}.png")
    pdf = os.path.join(OUT, f"report_{uid}.pdf")
    img.save(png, "PNG")
    img.convert("RGB").save(pdf, "PDF", resolution=150)
    return png, pdf


def build_growth_chart(snaps: list, uid: str) -> str | None:
    try:
        xs = [datetime.fromisoformat(s["ts"]) for s in snaps]
        ys = [int(s.get("followerCount") or 0) for s in snaps]
    except Exception:
        return None
    if len(xs) < 2:
        return None
    plt.figure(figsize=(9, 4.8), facecolor="#0d111e")
    ax = plt.gca()
    ax.set_facecolor("#0d111e")
    ax.plot(xs, ys, color="#00e6c3", linewidth=3, marker="o", markersize=5, markerfacecolor="#ff3c64")
    ax.fill_between(xs, ys, min(ys), color="#00e6c3", alpha=0.12)
    for spine in ax.spines.values():
        spine.set_color("#2a2f45")
    ax.tick_params(colors="#9aa0b3")
    ax.grid(True, color="#1c2033", linewidth=0.8)
    title = f"Followers Growth  @{uid}"
    ax.set_title(title, color="#f5f5fa", fontproperties=_MPL_FONT, fontsize=16)
    ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda v, _: F.fmt_num(v).split(" ")[0]))
    plt.xticks(rotation=25)
    plt.tight_layout()
    path = os.path.join(OUT, f"growth_{uid}.png")
    plt.savefig(path, facecolor="#0d111e", dpi=130)
    plt.close()
    return path
