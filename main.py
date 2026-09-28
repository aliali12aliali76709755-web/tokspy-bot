import os
import threading
import time
import urllib.request
import logging
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as HTTPServer
import urllib.parse
import json
import re
import queue
import asyncio
import httpx
import pymongo
import certifi

LOG_BUFFER = deque(maxlen=200)

class BufferHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            LOG_BUFFER.append(msg)
        except Exception:
            pass

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
buf_handler = BufferHandler()
buf_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
root_logger.addHandler(buf_handler)

import bot
import tiktok_service as tk

# Load landing page HTML template
LANDING_HTML_PATH = os.path.join(os.path.dirname(__file__), "landing_page.html")
try:
    with open(LANDING_HTML_PATH, "r", encoding="utf-8") as f:
        LANDING_PAGE_HTML = f.read().encode("utf-8")
except Exception as e:
    root_logger.error("Failed to read landing_page.html: %s", e)
    LANDING_PAGE_HTML = b"<h1>TokSpy Telegram Bot</h1>"

VISIT_QUEUE = queue.Queue()

def visitor_flush_worker():
    """Worker thread that flushes visitor analytics to MongoDB periodically without blocking HTTP requests."""
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "tiktokbot")
    if not mongo_url:
        return
    
    col = None
    while True:
        try:
            if col is None:
                client = pymongo.MongoClient(mongo_url, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
                col = client[db_name]["web_stats"]

            items = []
            try:
                item = VISIT_QUEUE.get(timeout=2)
                items.append(item)
                while not VISIT_QUEUE.empty() and len(items) < 1000:
                    items.append(VISIT_QUEUE.get_nowait())
            except queue.Empty:
                pass

            if items:
                total_inc = 0
                clicks_inc = 0
                sources = {}
                for it in items:
                    if it.get("click"):
                        clicks_inc += 1
                    else:
                        total_inc += 1
                        ref = it.get("ref", "direct")
                        sources[ref] = sources.get(ref, 0) + 1

                update_dict = {}
                if total_inc > 0:
                    update_dict["total_visits"] = total_inc
                if clicks_inc > 0:
                    update_dict["bot_clicks"] = clicks_inc
                for s, cnt in sources.items():
                    safe_key = re.sub(r'[\.\$]', '_', s)[:50]
                    update_dict[f"sources.{safe_key}"] = cnt

                if update_dict:
                    col.update_one(
                        {"_id": "global"},
                        {
                            "$inc": update_dict,
                            "$set": {"last_visit": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                        },
                        upsert=True
                    )
        except Exception as e:
            root_logger.warning("visitor_flush_worker error: %s", e)
            col = None
            time.sleep(2)


class HealthHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/click":
            qs = urllib.parse.parse_qs(parsed.query)
            ref = qs.get("ref", ["direct"])[0]
            VISIT_QUEUE.put({"ref": ref, "click": True})
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        try:
            self._handle_get()
        except Exception as e:
            root_logger.exception("HealthHandler do_GET error: %s", e)
            try:
                err_payload = json.dumps({"ok": False, "error": str(e)}, default=str).encode("utf-8")
                self.send_response(500)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(err_payload)))
                self.end_headers()
                self.wfile.write(err_payload)
            except Exception:
                pass

    def _handle_get(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/click":
            qs = urllib.parse.parse_qs(parsed.query)
            ref = qs.get("ref", ["direct"])[0]
            VISIT_QUEUE.put({"ref": ref, "click": True})
            self.send_response(204)
            self.end_headers()
            return

        if parsed.path == "/logs":
            logs_text = "\n".join(LOG_BUFFER)
            payload = logs_text.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path in ("/api/stats", "/stats"):
            mongo_url = os.environ.get("MONGO_URL")
            db_name = os.environ.get("DB_NAME", "tiktokbot")
            try:
                client = pymongo.MongoClient(mongo_url, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=2000)
                doc = client[db_name]["web_stats"].find_one({"_id": "global"}) or {}
                doc["_id"] = str(doc.get("_id"))
                res = {"ok": True, "stats": doc}
            except Exception as e:
                res = {"ok": False, "error": str(e)}
            payload = json.dumps(res, ensure_ascii=False, default=str).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/debug_universal":
            qs = urllib.parse.parse_qs(parsed.query)
            t_url = qs.get("url", ["https://www.tiktok.com/@achievrich_/photo/7576393049769528598"])[0]
            from curl_cffi.requests import AsyncSession
            async def run_uni():
                try:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                    }
                    async with AsyncSession(impersonate="safari15_5") as s:
                        r = await s.get(t_url, headers=headers, timeout=10)
                        m = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', r.text, re.S)
                        if not m:
                            return {"found": False, "len": len(r.text)}
                        raw = json.loads(m.group(1))
                        scope = raw.get("__DEFAULT_SCOPE__", {})
                        # find all video-detail or post objects in scope
                        v_detail = scope.get("webapp.video-detail") or scope.get("webapp.user-detail") or {}
                        item_info = v_detail.get("itemInfo", {})
                        item_struct = item_info.get("itemStruct", {})
                        # recursively search for playCount or diggCount
                        def find_counts(d, depth=0):
                            res = {}
                            if depth > 5 or not isinstance(d, dict):
                                return res
                            for k, v in d.items():
                                if k in ("playCount", "diggCount", "commentCount", "shareCount", "collectCount", "stats", "statsV2"):
                                    res[k] = v
                                elif isinstance(v, dict):
                                    sub = find_counts(v, depth+1)
                                    if sub:
                                        res[k] = sub
                            return res
                        return {
                            "found": True,
                            "scope_keys": list(scope.keys()),
                            "stats": item_struct.get("stats"),
                            "recursive_counts": find_counts(scope)
                        }
                except Exception as e:
                    return {"err": str(e)}
            res = asyncio.run(run_uni())
            payload = json.dumps(res, ensure_ascii=False, default=str).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/debug_profile":
            qs = urllib.parse.parse_qs(parsed.query)
            u = qs.get("u", ["wirtschaftsfakten"])[0]
            async def run_prof():
                try:
                    p = await tk.fetch_profile(u)
                    return {"ok": bool(p), "profile": p}
                except Exception as e:
                    import traceback
                    return {"ok": False, "error": str(e), "trace": traceback.format_exc()}
            res = asyncio.run(run_prof())
            payload = json.dumps(res, ensure_ascii=True, default=str).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path == "/debug_dl":
            qs = urllib.parse.parse_qs(parsed.query)
            url = qs.get("url", ["https://vm.tiktok.com/ZN86HLRrs/"])[0]
            
            async def run_dbg():
                dbg_res = {}
                try:
                    data = await tk.download_video(url)
                    dbg_res["tk_download"] = bool(data)
                    if data:
                        return {
                            "ok": True,
                            "id": data.get("id"),
                            "views": data.get("play_count"),
                            "likes": data.get("digg_count"),
                            "comments": data.get("comment_count"),
                            "saves": data.get("collect_count"),
                            "shares": data.get("share_count"),
                            "create_time": data.get("create_time"),
                            "author": data.get("author"),
                            "images_count": len(data.get("images") or []),
                            "has_video_path": bool(data.get("video_path")),
                            "has_play": bool(data.get("play")),
                        }
                except Exception as e:
                    dbg_res["tk_download_err"] = str(e)

                # Test httpx to tikwm
                try:
                    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as cx:
                        r = await cx.post("https://www.tikwm.com/api/", data={"url": url, "hd": "1"}, headers={"User-Agent": "Mozilla/5.0"})
                        dbg_res["tikwm_httpx_status"] = r.status_code
                        dbg_res["tikwm_httpx_code"] = r.json().get("code") if r.status_code == 200 else r.text[:150]
                except Exception as e:
                    dbg_res["tikwm_httpx_err"] = str(e)

                # Test tikvideo.app
                try:
                    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as cx:
                        r = await cx.post("https://tikvideo.app/api/ajaxSearch", data={"q": url, "lang": "en"}, headers={"User-Agent": "Mozilla/5.0"})
                        dbg_res["tikvideo_status"] = r.status_code
                        dbg_res["tikvideo_has_dl"] = "tik-button-dl" in r.text or "snapcdn.app" in r.text
                except Exception as e:
                    dbg_res["tikvideo_err"] = str(e)

                # Test non-www tikwm
                try:
                    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as cx:
                        r = await cx.post("https://tikwm.com/api/", data={"url": url, "hd": "1"}, headers={"User-Agent": "Mozilla/5.0"})
                        dbg_res["tikwm_nowww_status"] = r.status_code
                except Exception as e:
                    dbg_res["tikwm_nowww_err"] = str(e)

                return {"ok": False, "diagnostics": dbg_res}

            try:
                res = asyncio.run(run_dbg())
                payload = json.dumps(res, ensure_ascii=True, default=str).encode('utf-8')
            except Exception as e:
                import traceback
                payload = json.dumps({"ok": False, "err": str(e), "trace": traceback.format_exc()}).encode('utf-8')

            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        # Track visitor unless internal monitor/keepalive
        ua = self.headers.get("User-Agent", "")
        if "TokSpyKeepAlive" not in ua and "Render" not in ua:
            qs = urllib.parse.parse_qs(parsed.query)
            ref = qs.get("ref", ["direct"])[0]
            VISIT_QUEUE.put({"ref": ref, "click": False})

        # Serve landing page for / and any other route
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(LANDING_PAGE_HTML)))
        self.end_headers()
        self.wfile.write(LANDING_PAGE_HTML)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(LANDING_PAGE_HTML)))
        self.end_headers()

    def log_message(self, format, *args):
        root_logger.info("HTTP %s - " + format, self.address_string(), *args)

def run_http_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

def keep_alive():
    """Ping the service every 120s to ensure Render never puts the instance to sleep."""
    url = "https://tokspy-telegram-bot.onrender.com"
    time.sleep(30)
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TokSpyKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                pass
        except Exception as e:
            root_logger.warning("KeepAlive ping notice: %s", e)
        time.sleep(120)

def run_bot_supervised():
    """Supervisor thread to auto-restart the bot immediately if it ever crashes."""
    while True:
        try:
            root_logger.info("Starting bot application (supervised)...")
            bot.main()
        except (KeyboardInterrupt, SystemExit):
            root_logger.info("Bot stopped intentionally.")
            break
        except Exception as e:
            root_logger.critical("Bot process crashed: %s. Auto-recovering in 3 seconds...", e, exc_info=True)
            time.sleep(3)

if __name__ == "__main__":
    t_flush = threading.Thread(target=visitor_flush_worker, daemon=True)
    t_flush.start()

    t_http = threading.Thread(target=run_http_server, daemon=True)
    t_http.start()

    t_ping = threading.Thread(target=keep_alive, daemon=True)
    t_ping.start()

    run_bot_supervised()
