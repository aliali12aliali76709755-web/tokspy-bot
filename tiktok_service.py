"""TikTok public-data service.

Primary source: direct scrape of the public profile page
(`__UNIVERSAL_DATA_FOR_REHYDRATION__`), which exposes every public profile
field. Stats fall back to tikwm.com for exact counts. Video download (no
watermark) uses tikwm.com. All data used here is publicly visible on the
profile itself.
"""
import os
import re
import json
import asyncio
import logging
import tempfile
import httpx

log = logging.getLogger("tiktokbot.service")

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


def _b64_decode(token: str) -> str:
    try:
        token = token.rstrip("/").split("/")[-1]
        missing = len(token) % 4
        if missing:
            token += "=" * (4 - missing)
        import base64
        decoded = base64.b64decode(token).decode("utf-8", "ignore")
        if decoded.startswith("http"):
            return decoded
    except Exception:
        pass
    return ""


async def _scrape_ssstik(url: str) -> dict | None:
    """Scrape photo images / media from SSSTik."""
    try:
        from bs4 import BeautifulSoup
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome110") as s:
            r_init = await s.get("https://ssstik.io/en", timeout=10)
            tt = re.search(r'data-tt="([^"]+)"', r_init.text)
            tt_val = tt.group(1) if tt else "0"
            r_post = await s.post(
                "https://ssstik.io/abc?url=dl",
                data={"id": url, "locale": "en", "tt": tt_val},
                headers={"hx-request": "true", "hx-target": "target", "hx-current-url": "https://ssstik.io/en"},
                timeout=15
            )
            soup = BeautifulSoup(r_post.text, "html.parser")
            
            t_el = soup.select_one(".maintext, p.maintext, h2")
            title = t_el.get_text(strip=True) if t_el else ""
            
            raw_links = []
            for a in soup.find_all("a"):
                href = a.get("href", "")
                if "tikcdn.io/ssstik/" in href and "/m/" not in href and "/a/" not in href and "css" not in href:
                    raw_links.append(href)
            
            images = []
            for link in raw_links:
                dec = _b64_decode(link)
                if dec and dec not in images:
                    images.append(dec)
                elif link and link not in images:
                    images.append(link)

            music_url = None
            for a in soup.find_all("a"):
                href = a.get("href", "")
                if "/m/" in href:
                    dec = _b64_decode(href)
                    music_url = dec or href
                    break
                    
            if images:
                return {
                    "title": title,
                    "images": images,
                    "music": music_url,
                }
    except Exception as e:
        log.warning("SSSTik scraper error: %s", e)
    return None


async def download_video(url: str) -> dict | None:
    """Download TikTok post (video or photo slideshow) with reliable multi-engine fallback.
    Returns normalized dictionary with metadata, play/images/video_path.
    """
    url = (url or "").strip()
    if not url:
        return None

    # Step 1: Detect if photo and resolve redirects
    is_photo = ("/photo/" in url.lower())
    real_url = url
    post_id = ""
    author_uid = ""

    mobile_headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    item_struct = None
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="safari15_5") as s:
            r = await s.get(url, headers=mobile_headers, allow_redirects=True, timeout=10)
            real_url = r.url.split("?")[0]
            if "/photo/" in real_url.lower():
                is_photo = True
            
            m_id = re.search(r'/(?:video|photo)/(\d+)', real_url)
            if m_id:
                post_id = m_id.group(1)
            m_u = re.search(r'tiktok\.com/@([\w\.\-]+)', real_url)
            if m_u:
                author_uid = m_u.group(1)

            # Check if page has api-data JSON
            if "?" in r.url or real_url != url:
                r2 = await s.get(real_url, headers=mobile_headers, timeout=10)
                html = r2.text
            else:
                html = r.text

            m = re.search(r'<script id="api-data"[^>]*>(.*?)</script>', html, re.S)
            if m:
                raw_json = json.loads(m.group(1))
                item_struct = raw_json.get("videoDetail", {}).get("itemInfo", {}).get("itemStruct")
    except Exception as e:
        log.warning("Direct scrape error for %s: %s", url, e)

    # Step 2: If photo post, extract images via direct scrape or SSSTik
    if is_photo or (item_struct and item_struct.get("imagePost", {}).get("images")):
        # Method A: Direct itemStruct images
        if item_struct and item_struct.get("imagePost", {}).get("images"):
            image_post = item_struct.get("imagePost", {})
            raw_images = image_post.get("images", [])
            image_urls = []
            for img in raw_images:
                u_list = img.get("imageURL", {}).get("urlList", [])
                if u_list:
                    image_urls.append(u_list[0])
            if image_urls:
                stats = item_struct.get("stats", {})
                author = item_struct.get("author", {})
                music_info = item_struct.get("music", {})
                return {
                    "id": str(item_struct.get("id") or post_id or ""),
                    "title": item_struct.get("desc") or "",
                    "play": None,
                    "video_path": None,
                    "images": image_urls,
                    "music": music_info.get("playUrl"),
                    "music_info": {"play": music_info.get("playUrl"), "title": music_info.get("title")},
                    "author": {"unique_id": author.get("uniqueId", author_uid), "nickname": author.get("nickname", author_uid)},
                    "create_time": int(item_struct.get("createTime") or 0) if item_struct.get("createTime") else None,
                    "play_count": stats.get("playCount", 0),
                    "digg_count": stats.get("diggCount", 0),
                    "comment_count": stats.get("commentCount", 0),
                    "share_count": stats.get("shareCount", 0),
                    "collect_count": stats.get("collectCount", 0),
                    "download_count": 0,
                }

        # Method B: SSSTik scraper for photo slides
        ss = await _scrape_ssstik(url)
        if ss and ss.get("images"):
            prof = await fetch_profile(author_uid) if author_uid else None
            author_nick = (prof.get("nickname") if prof else "") or author_uid
            return {
                "id": post_id or "",
                "title": ss.get("title") or "",
                "play": None,
                "video_path": None,
                "images": ss["images"],
                "music": ss.get("music"),
                "music_info": {"play": ss.get("music")},
                "author": {"unique_id": author_uid, "nickname": author_nick},
                "create_time": None,
                "play_count": 0,
                "digg_count": 0,
                "comment_count": 0,
                "share_count": 0,
                "collect_count": 0,
                "download_count": 0,
            }

    # Step 3: For videos (and photo fallback), download via yt-dlp
    try:
        import yt_dlp
        loop = asyncio.get_event_loop()
        tmp_dir = tempfile.mkdtemp(prefix="tokspy_")
        out_tmpl = os.path.join(tmp_dir, "%(id)s.%(ext)s")

        ytdl_target = real_url
        if is_photo and post_id and author_uid:
            ytdl_target = f"https://www.tiktok.com/@{author_uid}/video/{post_id}"

        def _download_ytdl():
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "outtmpl": out_tmpl,
                "format": "bestvideo+bestaudio/best",
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(ytdl_target, download=True)
                fpath = ydl.prepare_filename(info)
                return info, fpath

        info, video_path = await loop.run_in_executor(None, _download_ytdl)
        if os.path.exists(video_path):
            uid = (item_struct.get("author", {}).get("uniqueId") if item_struct else "") or author_uid or info.get("uploader_id") or info.get("uploader") or ""
            author_nick = (item_struct.get("author", {}).get("nickname") if item_struct else "") or info.get("uploader") or uid
            stats = item_struct.get("stats", {}) if item_struct else {}

            return {
                "id": str(info.get("id") or post_id or (item_struct.get("id") if item_struct else "") or ""),
                "title": (item_struct.get("desc") if item_struct else "") or info.get("title") or info.get("description") or "",
                "play": info.get("url"),
                "video_path": video_path,
                "images": [],
                "music": None,
                "author": {
                    "unique_id": uid,
                    "nickname": author_nick,
                },
                "create_time": (int(item_struct.get("createTime") or 0) if item_struct else None) or info.get("timestamp"),
                "duration": info.get("duration"),
                "play_count": stats.get("playCount") or info.get("view_count", 0),
                "digg_count": stats.get("diggCount") or info.get("like_count", 0),
                "comment_count": stats.get("commentCount") or info.get("comment_count", 0),
                "share_count": stats.get("shareCount") or info.get("repost_count", 0),
                "collect_count": stats.get("collectCount", 0),
                "download_count": 0,
            }
    except Exception as e:
        log.warning("yt-dlp download failed for %s: %s", url, e)

    # Step 4: If yt-dlp failed, check direct item_struct video URLs
    if item_struct:
        video = item_struct.get("video", {})
        play_url = video.get("playAddr") or video.get("downloadAddr")
        if not play_url and video.get("bitrate"):
            play_url = video["bitrate"][0].get("playAddr", {}).get("urlList", [None])[0]
        if play_url:
            stats = item_struct.get("stats", {})
            author = item_struct.get("author", {})
            music_info = item_struct.get("music", {})
            return {
                "id": str(item_struct.get("id") or ""),
                "title": item_struct.get("desc") or "",
                "play": play_url,
                "video_path": None,
                "images": [],
                "music": music_info.get("playUrl"),
                "music_info": {
                    "play": music_info.get("playUrl"),
                    "title": music_info.get("title"),
                    "author": music_info.get("authorName"),
                },
                "author": {
                    "unique_id": author.get("uniqueId", author_uid),
                    "nickname": author.get("nickname", author_uid),
                },
                "create_time": int(item_struct.get("createTime") or 0) if item_struct.get("createTime") else None,
                "duration": video.get("duration"),
                "play_count": stats.get("playCount", 0),
                "digg_count": stats.get("diggCount", 0),
                "comment_count": stats.get("commentCount", 0),
                "share_count": stats.get("shareCount", 0),
                "collect_count": stats.get("collectCount", 0),
                "download_count": 0,
            }

    # Step 5: tikwm fallback
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120") as s:
            r = await s.post(
                "https://www.tikwm.com/api/",
                data={"url": url, "hd": "1"},
                timeout=12,
            )
            if r.status_code == 200:
                j = r.json()
                if j.get("code") == 0:
                    return j["data"]
    except Exception:
        pass

    return None
