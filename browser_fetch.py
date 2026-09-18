"""Headless-browser fetch of a public TikTok user's latest posts.

Loads the public profile in Chromium (no login) and intercepts the
`item_list` XHR that TikTok itself issues, returning the public video list.
This is the same public data any visitor's browser receives.
"""
import re
import json
import os
import glob
import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
    re.S,
)

_pw = None
_br = None
_stealth = Stealth()
_lock = asyncio.Lock()


def _find_executable():
    for pat in (
        "/pw-browsers/chromium-*/chrome-linux/chrome",
        "/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell",
    ):
        m = sorted(glob.glob(pat))
        if m:
            return m[-1]
    return None


async def _ensure():
    global _pw, _br
    if _br is not None and _br.is_connected():
        return
    _pw = await async_playwright().start()
    kwargs = dict(
        headless=True,
        args=["--no-sandbox"],
    )
    exe = _find_executable()
    if exe and os.path.exists(exe):
        kwargs["executable_path"] = exe
    _br = await _pw.chromium.launch(**kwargs)


def _norm(it: dict) -> dict:
    stats = it.get("statsV2") or it.get("stats") or {}
    img = (it.get("imagePost") or {}).get("images") or []
    images = []
    for i in img:
        lst = (i.get("imageURL") or {}).get("urlList") or []
        if lst:
            images.append(lst[0])
    video = it.get("video") or {}
    music = it.get("music") or {}

    def _i(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    return {
        "id": str(it.get("id") or ""),
        "title": it.get("desc") or "",
        "play": None,  # no-watermark URL fetched separately via tikwm download
        "cover": video.get("cover") or video.get("originCover"),
        "images": images,
        "music": music.get("playUrl"),
        "create_time": _i(it.get("createTime")),
        "play_count": _i(stats.get("playCount")),
        "digg_count": _i(stats.get("diggCount")),
        "comment_count": _i(stats.get("commentCount")),
        "share_count": _i(stats.get("shareCount")),
        "collect_count": _i(stats.get("collectCount")),
    }


async def fetch_profile_browser(username: str) -> tuple[dict | None, dict | None]:
    """Fetch public TikTok user profile and stats using headless Chromium with mobile emulation."""
    username = (username or "").lstrip("@").strip()
    if not username:
        return None, None
    async with _lock:
        ctx = None
        try:
            await _ensure()
            device = _pw.devices.get("iPhone 14", {})
            ctx = await _br.new_context(**device)
            page = await ctx.new_page()
            try:
                await page.goto(
                    f"https://www.tiktok.com/@{username}",
                    timeout=20000,
                )
            except Exception:
                pass

            for _ in range(12):
                await page.wait_for_timeout(350)
                try:
                    html = await page.content()
                    m = _RE.search(html)
                    if m:
                        data = json.loads(m.group(1))
                        info = (
                            data.get("__DEFAULT_SCOPE__", {})
                            .get("webapp.user-detail", {})
                            .get("userInfo", {})
                        )
                        if info.get("user"):
                            user = info["user"]
                            stats = info.get("statsV2") or info.get("stats") or {}
                            return user, stats
                except Exception:
                    pass
            return None, None
        except Exception:
            return None, None
        finally:
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass


async def fetch_posts(username: str, count: int = 6):
    """Return list of latest public posts, or None on failure."""
    username = (username or "").lstrip("@").strip()
    if not username:
        return None
    async with _lock:
        ctx = None
        try:
            await _ensure()
            ctx = await _br.new_context(
                user_agent=_UA, viewport={"width": 1280, "height": 800}, locale="en-US"
            )
            page = await ctx.new_page()
            await _stealth.apply_stealth_async(page)
            box = {"items": None}

            async def on_resp(resp):
                if "item_list" in resp.url and box["items"] is None:
                    try:
                        j = await resp.json()
                        if j.get("itemList"):
                            box["items"] = j["itemList"]
                    except Exception:
                        pass

            page.on("response", on_resp)
            try:
                await page.goto(
                    f"https://www.tiktok.com/@{username}",
                    wait_until="domcontentloaded", timeout=40000,
                )
            except Exception:
                pass
            # nudge lazy loading of the video grid
            for _ in range(3):
                if box["items"] is not None:
                    break
                try:
                    await page.mouse.wheel(0, 1500)
                except Exception:
                    pass
                await page.wait_for_timeout(700)
            for _ in range(30):
                if box["items"] is not None:
                    break
                await page.wait_for_timeout(500)
            items = box["items"]
            if items is None:
                return None
            return [_norm(it) for it in items[:count]]
        except Exception:
            return None
        finally:
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass
