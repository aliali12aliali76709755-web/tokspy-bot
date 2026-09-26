import os
import threading
import time
import urllib.request
import logging
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
import json
import re
import queue
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
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/click":
            qs = urllib.parse.parse_qs(parsed.query)
            ref = qs.get("ref", ["direct"])[0]
            VISIT_QUEUE.put({"ref": ref, "click": True})
            self.send_response(204)
            self.end_headers()
            return

        if parsed.path == "/logs":
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            logs_text = "\n".join(LOG_BUFFER)
            self.wfile.write(logs_text.encode('utf-8'))
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
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
            return

        if parsed.path == "/debug_dl":
            qs = urllib.parse.parse_qs(parsed.query)
            url = qs.get("url", ["https://vm.tiktok.com/ZN86HLRrs/"])[0]
            
            import asyncio
            import tiktok_service as tk
            async def run_dbg():
                try:
                    data = await tk.download_video(url)
                    if data:
                        vpath = data.get("video_path")
                        has_vpath = bool(vpath and os.path.exists(vpath))
                        if vpath and os.path.exists(vpath):
                            try:
                                os.remove(vpath)
                            except Exception:
                                pass
                        return {
                            "ok": True,
                            "id": data.get("id"),
                            "title": data.get("title"),
                            "author": data.get("author"),
                            "images_count": len(data.get("images", [])),
                            "first_image": data["images"][0][:80] if data.get("images") else None,
                            "has_video_file": has_vpath,
                            "play": data.get("play")[:80] if data.get("play") else None,
                            "play_count": data.get("play_count"),
                            "digg_count": data.get("digg_count"),
                        }
                    return {"ok": False, "error": "tk.download_video returned None"}
                except Exception as e:
                    return {"ok": False, "error": str(e)}

            res = asyncio.run(run_dbg())
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))
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
        pass

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
