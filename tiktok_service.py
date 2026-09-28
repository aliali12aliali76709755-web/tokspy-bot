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
import time
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


def extract_snowflake_timestamp(post_id: str | int | None) -> int | None:
    """Extract creation timestamp from TikTok 64-bit snowflake ID."""
    if not post_id:
        return None
    try:
        pid = int(str(post_id).strip())
        if pid > 1000000000000000:
            ts = pid >> 32
            if 1451606400 <= ts <= 2051222400:  # Valid Unix timestamp 2016-2035
                return ts
    except Exception:
        pass
    return None


async def fetch_profile(username: str) -> dict | None:
    """Return a normalized profile dict for a username, or None if not found."""
    username = clean_username(username)
    if not username:
        return None
    user, stats = None, None

    # 1) Countik public API (fast, reliable on datacenter IPs without blocking)
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120") as s:
            rc = await s.get(
                f"https://countik.com/api/exist/{username}",
                timeout=10,
            )
            if rc.status_code == 200:
                cj = rc.json()
                if cj.get("status") == "success":
                    uid_str = str(cj.get("id") or "")
                    ctime = extract_snowflake_timestamp(uid_str)
                    user = {
                        "uniqueId": cj.get("uniqueId") or username,
                        "id": uid_str,
                        "secUid": cj.get("sec_uid", ""),
                        "nickname": cj.get("nickname", ""),
                        "signature": cj.get("signature", ""),
                        "avatarThumb": cj.get("avatarThumb"),
                        "avatarMedium": cj.get("avatarThumb"),
                        "avatarLarger": cj.get("avatarThumb"),
                        "verified": bool(cj.get("verified")),
                        "createTime": ctime,
                    }
                    stats = {
                        "followerCount": cj.get("followerCount", 0),
                        "followingCount": cj.get("followingCount", 0),
                        "heartCount": cj.get("heartCount", 0),
                        "videoCount": cj.get("videoCount", 0),
                        "diggCount": 0,
                        "friendCount": 0,
                    }
    except Exception as e:
        log.warning("Countik fetch_profile error for %s: %s", username, e)

    # 2) Direct scrape with curl_cffi (rich fields, 0.4s fast bypass)
    if user is None or not stats or not stats.get("followerCount"):
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

    # 3) tikwm fallback / stats enrichment
    if user is None or not stats or not stats.get("followerCount"):
        try:
            from curl_cffi.requests import AsyncSession
            async with AsyncSession(impersonate="chrome120") as s:
                r = await s.post(
                    "https://www.tikwm.com/api/user/info",
                    data={"unique_id": username},
                    timeout=10,
                )
                if r.status_code == 200:
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

    # 4) Headless browser fallback
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
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120") as s:
            r = await s.get(
                "https://www.tikwm.com/api/user/search",
                params={"keywords": keywords, "count": count},
                timeout=12,
            )
            if r.status_code == 200:
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
    except Exception as e:
        log.warning("search_users error: %s", e)
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


async def _scrape_tikvideo(url: str) -> dict | None:
    """Download video or photo slideshow via tikvideo.app API with high-speed direct download."""
    try:
        from bs4 import BeautifulSoup
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as cx:
            r = await cx.post(
                "https://tikvideo.app/api/ajaxSearch",
                data={"q": url, "lang": "en"},
                headers={"User-Agent": _UA}
            )
            if r.status_code != 200:
                return None
            j = r.json()
            if j.get("status") != "ok":
                return None
            soup = BeautifulSoup(j.get("data", ""), "html.parser")

            title = ""
            h3 = soup.find("h3")
            if h3:
                title = h3.get_text(strip=True)

            cover = None
            img = soup.find("img")
            if img:
                cover = img.get("src")

            dl_links = []
            music_url = None
            images = []

            for a in soup.find_all("a"):
                href = a.get("href", "")
                txt = a.get_text(strip=True).lower()
                if not href or href.startswith("#") or href == "/":
                    continue
                if "mp3" in txt or "audio" in txt:
                    if not music_url:
                        music_url = href
                elif "photo" in txt or "image" in txt or "slide" in txt:
                    if href not in images:
                        images.append(href)
                elif "download" in txt or "mp4" in txt or "snapcdn" in href or "tiktokcdn" in href:
                    if href not in [x[0] for x in dl_links]:
                        dl_links.append((href, txt))

            if images:
                return {
                    "title": title,
                    "cover": cover,
                    "play": None,
                    "video_path": None,
                    "music": music_url,
                    "images": images,
                }

            best_link = None
            for href, txt in dl_links:
                if "tiktokcdn" in href:
                    best_link = href
                    break
            if not best_link and dl_links:
                best_link = dl_links[0][0]

            if best_link:
                tmp_dir = tempfile.mkdtemp(prefix="tokspy_")
                tmp_file = os.path.join(tmp_dir, f"{int(time.time()*1000)}.mp4")
                headers = {"User-Agent": _UA, "Referer": "https://www.tiktok.com/"}
                if "snapcdn" in best_link:
                    headers["Referer"] = "https://tikvideo.app/"
                resp = await cx.get(best_link, headers=headers, timeout=35)
                if resp.status_code == 200 and len(resp.content) > 10000:
                    with open(tmp_file, "wb") as f:
                        f.write(resp.content)
                    return {
                        "title": title,
                        "cover": cover,
                        "play": best_link,
                        "video_path": tmp_file,
                        "music": music_url,
                        "images": [],
                    }
    except Exception as e:
        log.warning("tikvideo scraper error: %s", e)
    return None


async def _scrape_musicaldown(url: str) -> dict | None:
    """Download video via musicaldown.com engine."""
    try:
        from bs4 import BeautifulSoup
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as cx:
            r1 = await cx.get("https://musicaldown.com/en", headers={"User-Agent": _UA})
            soup = BeautifulSoup(r1.text, "html.parser")
            inputs = {inp.get("name"): inp.get("value", "") for inp in soup.find_all("input") if inp.get("name")}
            if not inputs:
                return None
            inputs[list(inputs.keys())[0]] = url
            r2 = await cx.post("https://musicaldown.com/download", data=inputs, headers={"User-Agent": _UA, "Referer": "https://musicaldown.com/en"})
            if r2.status_code != 200:
                return None
            soup2 = BeautifulSoup(r2.text, "html.parser")

            dl_url = None
            music_url = None
            images = []

            for a in soup2.find_all("a"):
                txt = a.get_text(strip=True)
                href = a.get("href", "")
                if not href or href.startswith("#") or href.startswith("/"):
                    continue
                if "Download MP4" in txt and "Watermark" not in txt and not dl_url:
                    dl_url = href
                elif "Download MP3" in txt and not music_url:
                    music_url = href
                elif "download-photo" in href or "slide" in href or "image" in txt.lower():
                    if href not in images:
                        images.append(href)

            if images:
                return {
                    "title": "",
                    "play": None,
                    "video_path": None,
                    "music": music_url,
                    "images": images,
                }

            if dl_url:
                tmp_dir = tempfile.mkdtemp(prefix="tokspy_")
                tmp_file = os.path.join(tmp_dir, f"{int(time.time()*1000)}.mp4")
                resp = await cx.get(dl_url, headers={"Referer": "https://musicaldown.com/"}, timeout=35)
                if resp.status_code == 200 and len(resp.content) > 10000:
                    with open(tmp_file, "wb") as f:
                        f.write(resp.content)
                    return {
                        "title": "",
                        "play": dl_url,
                        "video_path": tmp_file,
                        "music": music_url,
                        "images": [],
                    }
    except Exception as e:
        log.warning("musicaldown scraper error: %s", e)
    return None


def extract_item_struct_from_html(html: str) -> dict | None:
    """Extract itemStruct post details from TikTok UNIVERSAL_DATA or api-data script tags."""
    if not html:
        return None
    # 1. Try __UNIVERSAL_DATA_FOR_REHYDRATION__
    m_uni = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
    if m_uni:
        try:
            raw_uni = json.loads(m_uni.group(1))
            scope = raw_uni.get("__DEFAULT_SCOPE__", {})
            for key in ("webapp.reflow.video.detail", "webapp.video-detail"):
                it = scope.get(key, {}).get("itemInfo", {}).get("itemStruct")
                if it:
                    return it
            for k, val in scope.items():
                if isinstance(val, dict):
                    it = val.get("itemInfo", {}).get("itemStruct")
                    if it:
                        return it
        except Exception:
            pass

    # 2. Try api-data
    m_api = re.search(r'<script id="api-data"[^>]*>(.*?)</script>', html, re.S)
    if m_api:
        try:
            raw_api = json.loads(m_api.group(1))
            it = raw_api.get("videoDetail", {}).get("itemInfo", {}).get("itemStruct")
            if it:
                return it
        except Exception:
            pass

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

    m_id_init = re.search(r'/(?:video|photo)/(\d+)', url)
    if m_id_init:
        post_id = m_id_init.group(1)
    m_u_init = re.search(r'tiktok\.com/@([\w\.\-]+)', url)
    if m_u_init:
        author_uid = m_u_init.group(1)

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

            # Check if page has api-data JSON or UNIVERSAL_DATA
            if "?" in r.url or real_url != url:
                r2 = await s.get(real_url, headers=mobile_headers, timeout=10)
                html = r2.text
            else:
                html = r.text

            item_struct = extract_item_struct_from_html(html)
    except Exception as e:
        log.warning("Direct scrape error for %s: %s", url, e)

    # Secondary redirect resolver if short URL was not resolved
    if real_url == url and ("vt.tiktok.com" in url or "vm.tiktok.com" in url or "v.tiktok.com" in url):
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as cx:
                r_redir = await cx.get(url, headers=mobile_headers)
                real_url = str(r_redir.url).split("?")[0]
                if "/photo/" in real_url.lower():
                    is_photo = True
                m_id = re.search(r'/(?:video|photo)/(\d+)', real_url)
                if m_id:
                    post_id = m_id.group(1)
                m_u = re.search(r'tiktok\.com/@([\w\.\-]+)', real_url)
                if m_u:
                    author_uid = m_u.group(1)
        except Exception:
            pass

    snowflake_ts = extract_snowflake_timestamp(post_id)

    # Step 2: Query TikWM via curl_cffi (impersonate="chrome120") for full metadata and media
    tikwm_meta = None
    try:
        from curl_cffi.requests import AsyncSession
        async with AsyncSession(impersonate="chrome120") as s:
            # Query with original url first (TikWM resolves short links via its own clean proxy network)
            r = await s.post("https://www.tikwm.com/api/", data={"url": url, "hd": "1"}, timeout=12)
            if r.status_code == 200:
                j = r.json()
                if j.get("code") == 0 and j.get("data"):
                    tikwm_meta = j["data"]
            # Fallback to real_url if different and valid
            if not tikwm_meta and real_url and real_url != url and ("/video/" in real_url or "/photo/" in real_url):
                r2 = await s.post("https://www.tikwm.com/api/", data={"url": real_url, "hd": "1"}, timeout=12)
                if r2.status_code == 200:
                    j2 = r2.json()
                    if j2.get("code") == 0 and j2.get("data"):
                        tikwm_meta = j2["data"]
    except Exception as e:
        log.warning("tikwm api query error: %s", e)

    meta_id = (tikwm_meta.get("id") if tikwm_meta else None) or (item_struct.get("id") if item_struct else None) or post_id or ""
    if not snowflake_ts and meta_id:
        snowflake_ts = extract_snowflake_timestamp(meta_id)

    meta_views = (_to_int(tikwm_meta.get("play_count")) if tikwm_meta else 0) or (_to_int(item_struct.get("stats", {}).get("playCount", 0)) if item_struct else 0)
    meta_likes = (_to_int(tikwm_meta.get("digg_count")) if tikwm_meta else 0) or (_to_int(item_struct.get("stats", {}).get("diggCount", 0)) if item_struct else 0)
    meta_comments = (_to_int(tikwm_meta.get("comment_count")) if tikwm_meta else 0) or (_to_int(item_struct.get("stats", {}).get("commentCount", 0)) if item_struct else 0)
    meta_shares = (_to_int(tikwm_meta.get("share_count")) if tikwm_meta else 0) or (_to_int(item_struct.get("stats", {}).get("shareCount", 0)) if item_struct else 0)
    meta_saves = (_to_int(tikwm_meta.get("collect_count")) if tikwm_meta else 0) or (_to_int(item_struct.get("stats", {}).get("collectCount", 0)) if item_struct else 0)
    meta_downloads = (_to_int(tikwm_meta.get("download_count")) if tikwm_meta else 0)
    meta_create_time = (_to_int(tikwm_meta.get("create_time")) if tikwm_meta else None) or (_to_int(item_struct.get("createTime")) if item_struct else None) or snowflake_ts

    author_info = (tikwm_meta.get("author") if tikwm_meta else None) or (item_struct.get("author") if item_struct else None) or {}
    meta_author_uid = author_info.get("unique_id") or author_info.get("uniqueId") or author_uid
    meta_author_nick = author_info.get("nickname") or ""
    meta_title = (tikwm_meta.get("title") if tikwm_meta else None) or (item_struct.get("desc") if item_struct else None) or ""
    meta_music = (tikwm_meta.get("music") if tikwm_meta else None) or (item_struct.get("music", {}).get("playUrl") if item_struct else None)
    meta_music_info = (tikwm_meta.get("music_info") if tikwm_meta else None) or ({"play": meta_music} if meta_music else {})

    if not meta_author_nick and meta_author_uid:
        prof = await fetch_profile(meta_author_uid)
        if prof:
            meta_author_nick = prof.get("nickname") or meta_author_uid
            if not author_info.get("id"):
                author_info["id"] = prof.get("id", "")

    # Step 3: Check if Photo post / Slideshow
    images = (tikwm_meta.get("images") if tikwm_meta else None) or []
    if not images and item_struct and item_struct.get("imagePost", {}).get("images"):
        for img in item_struct["imagePost"]["images"]:
            u_list = img.get("imageURL", {}).get("urlList", [])
            if u_list and u_list[0] not in images:
                images.append(u_list[0])

    if not images and is_photo:
        ss = await _scrape_ssstik(real_url)
        if ss and ss.get("images"):
            images = ss["images"]
            if not meta_music:
                meta_music = ss.get("music")
                meta_music_info = {"play": meta_music}
            if not meta_title:
                meta_title = ss.get("title") or ""

    if not images and is_photo:
        tv = await _scrape_tikvideo(real_url)
        if tv and tv.get("images"):
            images = tv["images"]
            if not meta_music:
                meta_music = tv.get("music")
                meta_music_info = {"play": meta_music}
            if not meta_title:
                meta_title = tv.get("title") or ""

    if images:
        return {
            "id": meta_id,
            "title": meta_title,
            "play": None,
            "video_path": None,
            "images": images,
            "music": meta_music,
            "music_info": meta_music_info,
            "author": {"unique_id": meta_author_uid, "nickname": meta_author_nick, "id": author_info.get("id", "")},
            "create_time": meta_create_time,
            "play_count": meta_views,
            "digg_count": meta_likes,
            "comment_count": meta_comments,
            "share_count": meta_shares,
            "collect_count": meta_saves,
            "download_count": meta_downloads,
        }

    # Step 4: Video post -> Download video file
    video_path = None
    play_url = (tikwm_meta.get("play") if tikwm_meta else None) or (tikwm_meta.get("hdplay") if tikwm_meta else None)

    # Try downloading video from TikWM play link
    if play_url and "tiktokcdn" in play_url:
        try:
            tmp_dir = tempfile.mkdtemp(prefix="tokspy_")
            tmp_file = os.path.join(tmp_dir, f"{int(time.time()*1000)}.mp4")
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as cx:
                resp = await cx.get(play_url, headers={"User-Agent": _UA, "Referer": "https://www.tiktok.com/"})
                if resp.status_code == 200 and len(resp.content) > 10000:
                    with open(tmp_file, "wb") as f:
                        f.write(resp.content)
                    video_path = tmp_file
        except Exception as e:
            log.warning("tikwm direct video download error: %s", e)

    # Fallback Engine A: TikVideo (direct download to disk)
    if not video_path:
        tv = await _scrape_tikvideo(url)
        if tv:
            if tv.get("video_path") and os.path.exists(tv["video_path"]):
                video_path = tv["video_path"]
            if not play_url:
                play_url = tv.get("play")
            if not meta_title:
                meta_title = tv.get("title") or ""
            if not meta_music:
                meta_music = tv.get("music")
                meta_music_info = {"play": meta_music}

    # Fallback Engine B: MusicalDown (direct download to disk)
    if not video_path:
        md = await _scrape_musicaldown(url)
        if md:
            if md.get("video_path") and os.path.exists(md["video_path"]):
                video_path = md["video_path"]
            if not play_url:
                play_url = md.get("play")
            if not meta_music:
                meta_music = md.get("music")
                meta_music_info = {"play": meta_music}

    # Fallback Engine C: yt-dlp
    if not video_path:
        try:
            import yt_dlp
            loop = asyncio.get_event_loop()
            tmp_dir = tempfile.mkdtemp(prefix="tokspy_")
            out_tmpl = os.path.join(tmp_dir, "%(id)s.%(ext)s")

            def _download_ytdl():
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "outtmpl": out_tmpl,
                    "format": "bestvideo+bestaudio/best",
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(real_url, download=True)
                    fpath = ydl.prepare_filename(info)
                    return info, fpath

            info, fpath = await loop.run_in_executor(None, _download_ytdl)
            if os.path.exists(fpath):
                video_path = fpath
                if not play_url:
                    play_url = info.get("url")
                if not meta_views:
                    meta_views = info.get("view_count", 0)
                if not meta_likes:
                    meta_likes = info.get("like_count", 0)
                if not meta_comments:
                    meta_comments = info.get("comment_count", 0)
                if not meta_shares:
                    meta_shares = info.get("repost_count", 0)
                if not meta_create_time:
                    meta_create_time = info.get("timestamp") or snowflake_ts
        except Exception as e:
            log.warning("yt-dlp fallback failed: %s", e)

    if video_path or play_url:
        return {
            "id": meta_id,
            "title": meta_title,
            "play": play_url,
            "video_path": video_path,
            "images": [],
            "music": meta_music,
            "music_info": meta_music_info,
            "author": {"unique_id": meta_author_uid, "nickname": meta_author_nick, "id": author_info.get("id", "")},
            "create_time": meta_create_time,
            "play_count": meta_views,
            "digg_count": meta_likes,
            "comment_count": meta_comments,
            "share_count": meta_shares,
            "collect_count": meta_saves,
            "download_count": meta_downloads,
        }

    return None
