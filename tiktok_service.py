"""TikTok public-data service.

Primary source: direct scrape of the public profile page
(`__UNIVERSAL_DATA_FOR_REHYDRATION__`), which exposes every public profile
field. Stats fall back to tikwm.com for exact counts. Video download (no
watermark) uses tikwm.com. All data used here is publicly visible on the
profile itself.
"""
import re
import json
import httpx

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}
_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
    re.S,
)


def clean_username(text: str) -> str:
    text = (text or "").strip()
    m = re.search(r"tiktok\.com/@([\w\.\-]+)", text)
    if m:
        return m.group(1)
    return text.lstrip("@").strip().split("/")[0].split("?")[0]


def is_video_link(text: str) -> bool:
    t = (text or "").lower()
    return "tiktok.com" in t and ("/video/" in t or "/photo/" in t or "vm.tiktok" in t or "vt.tiktok" in t or "v.tiktok" in t)


def _to_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


async def fetch_profile(username: str) -> dict | None:
    """Return a normalized profile dict for a username, or None if not found."""
    username = clean_username(username)
    if not username:
        return None
    user, stats = None, None
    # 1) Direct scrape with curl_cffi (rich fields, 0.4s fast bypass)
    try:
        from curl_cffi.requests import AsyncSession
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with AsyncSession(impersonate="safari15_5") as s:
            r = await s.get(f"https://www.tiktok.com/@{username}", headers=headers, timeout=10)
            if r.status_code == 200:
                m = _RE.search(r.text)
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
    except Exception:
        pass

    # 2) tikwm fallback / stats enrichment (only if scrape incomplete)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as cx:
        if user is None or not stats or not stats.get("followerCount"):
            try:
                r = await cx.post(
                    "https://www.tikwm.com/api/user/info",
                    data={"unique_id": username},
                    headers={"User-Agent": _UA},
                )
                j = r.json()
                if j.get("code") == 0:
                    d = j["data"]
                    st = d.get("stats", {})
                    tikwm_stats = {
                        "followerCount": st.get("followerCount"),
                        "followingCount": st.get("followingCount"),
                        "heartCount": st.get("heartCount"),
                        "videoCount": st.get("videoCount"),
                        "diggCount": st.get("diggCount"),
                        "friendCount": st.get("friendCount", 0),
                    }
                    if user is None:
                        user = d.get("user", {})
                        stats = tikwm_stats
                    else:
                        stats = tikwm_stats
            except Exception:
                pass

    # 3) Headless browser fallback (bypasses TikTok WAF/Cloudflare)
    if user is None or not stats or not stats.get("followerCount"):
        try:
            import browser_fetch as BF
            u, s = await BF.fetch_profile_browser(username)
            if u:
                user = u
                stats = s
        except Exception:
            pass

    if not user:
        return None
    stats = stats or {}
    return _normalize(user, stats)


def _normalize(user: dict, stats: dict) -> dict:
    bl = user.get("bioLink") or {}
    ci = user.get("commerceUserInfo") or {}
    pt = user.get("profileTab") or {}
    return {
        "uniqueId": user.get("uniqueId", ""),
        "id": user.get("id", ""),
        "secUid": user.get("secUid", ""),
        "nickname": user.get("nickname", ""),
        "signature": user.get("signature", ""),
        "bioLink": bl.get("link"),
        "avatar": user.get("avatarLarger") or user.get("avatarMedium") or user.get("avatarThumb"),
        "verified": bool(user.get("verified")),
        "privateAccount": bool(user.get("privateAccount")),
        "secret": bool(user.get("secret")),
        "ftc": bool(user.get("ftc")),
        "isOrganization": _to_int(user.get("isOrganization")),
        "isADVirtual": bool(user.get("isADVirtual")),
        "ttSeller": bool(user.get("ttSeller")),
        "commerceUser": bool(ci.get("commerceUser")),
        "category": ci.get("category") or "",
        "openFavorite": bool(user.get("openFavorite")),
        "isEmbedBanned": bool(user.get("isEmbedBanned")),
        "storyStatus": _to_int(user.get("UserStoryStatus")),
        "region": user.get("region") or "",
        "language": user.get("language") or "",
        "relation": _to_int(user.get("relation")),
        "createTime": _to_int(user.get("createTime")),
        "nickNameModifyTime": _to_int(user.get("nickNameModifyTime")),
        "uniqueIdModifyTime": _to_int(user.get("uniqueIdModifyTime")),
        "commentSetting": user.get("commentSetting"),
        "duetSetting": user.get("duetSetting"),
        "stitchSetting": user.get("stitchSetting"),
        "downloadSetting": user.get("downloadSetting"),
        "followingVisibility": user.get("followingVisibility"),
        "suggestAccountBind": bool(user.get("suggestAccountBind")),
        "canExpPlaylist": bool(user.get("canExpPlaylist")),
        "profileEmbedPermission": user.get("profileEmbedPermission"),
        "showMusicTab": bool(pt.get("showMusicTab")),
        "showQuestionTab": bool(pt.get("showQuestionTab")),
        "showPlayListTab": bool(pt.get("showPlayListTab")),
        # stats
        "followerCount": _to_int(stats.get("followerCount")),
        "followingCount": _to_int(stats.get("followingCount")),
        "heartCount": _to_int(stats.get("heartCount") or stats.get("heart")),
        "videoCount": _to_int(stats.get("videoCount")),
        "diggCount": _to_int(stats.get("diggCount")),
        "friendCount": _to_int(stats.get("friendCount")),
    }


async def search_users(keywords: str, count: int = 20) -> list[dict]:
    """Search TikTok accounts by keyword/name. Returns lite profile dicts."""
    out = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as cx:
        try:
            r = await cx.get(
                "https://www.tikwm.com/api/user/search",
                params={"keywords": keywords, "count": count},
                headers={"User-Agent": _UA},
            )
            j = r.json()
            if j.get("code") == 0:
                for item in j["data"].get("user_list", []):
                    u = item.get("user", {})
                    st = item.get("stats", {})
                    out.append({
                        "uniqueId": u.get("uniqueId", ""),
                        "nickname": u.get("nickname", ""),
                        "avatar": u.get("avatarMedium") or u.get("avatarThumb"),
                        "verified": bool(u.get("verified")),
                        "region": u.get("region", ""),
                        "followerCount": _to_int(st.get("followerCount")),
                    })
        except Exception:
            pass
    return out


def _pick_media(item: dict) -> dict:
    """Normalize a tikwm story/post item into media fields."""
    return {
        "id": str(item.get("video_id") or item.get("id") or item.get("aweme_id") or ""),
        "title": item.get("title") or "",
        "play": item.get("play") or item.get("wmplay") or item.get("hdplay"),
        "cover": item.get("cover") or item.get("origin_cover") or item.get("ai_dynamic_cover"),
        "images": item.get("images") or [],
        "music": (item.get("music_info") or {}).get("play") or item.get("music"),
        "create_time": item.get("create_time"),
        "duration": item.get("duration"),
        "play_count": item.get("play_count"),
        "digg_count": item.get("digg_count"),
        "comment_count": item.get("comment_count"),
        "share_count": item.get("share_count"),
        "collect_count": item.get("collect_count"),
    }


async def fetch_stories(username: str) -> list[dict]:
    """Fetch currently-active public stories. Returns [] if none."""
    username = clean_username(username)
    out = []
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120") as s:
            r = await s.get(f"https://www.tikwm.com/api/user/story?unique_id={username}", timeout=15)
            if r.status_code == 200:
                j = r.json()
                if j.get("code") == 0:
                    for it in j["data"].get("videos", []):
                        m = _pick_media(it)
                        if m["id"]:
                            out.append(m)
    except Exception:
        pass
    return out


async def fetch_posts(username: str, count: int = 6):
    """Fetch latest public posts. Tries tikwm, then a headless browser.
    Returns list, or None if all sources fail."""
    username = clean_username(username)
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120") as s:
            r = await s.get(f"https://www.tikwm.com/api/user/posts?unique_id={username}&count={count}&cursor=0", timeout=10)
            if r.status_code == 200:
                j = r.json()
                if j.get("code") == 0:
                    vids = [_pick_media(it) for it in j["data"].get("videos", []) if (it.get("video_id") or it.get("id"))]
                    if vids:
                        return vids
    except Exception:
        pass
    # fallback: headless browser (free, no key, public data)
    try:
        import browser_fetch
        return await browser_fetch.fetch_posts(username, count)
    except Exception:
        return None


async def download_video(url: str) -> dict | None:
    """Return dict with no-watermark video info from tikwm, or None."""
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120") as s:
            r = await s.post(
                "https://www.tikwm.com/api/",
                data={"url": url, "hd": "1"},
                timeout=15,
            )
            if r.status_code == 200:
                j = r.json()
                if j.get("code") == 0:
                    return j["data"]
    except Exception:
        pass
    return None
