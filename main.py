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

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/logs":
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            logs_text = "\n".join(LOG_BUFFER)
            self.wfile.write(logs_text.encode('utf-8'))
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

        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'{"status": "ok", "bot": "TokSpy", "state": "running"}')

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def run_http_server():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

def keep_alive():
    url = "https://tokspy-telegram-bot.onrender.com"
    time.sleep(120)
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TokSpyKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                pass
        except Exception:
            pass
        time.sleep(600)

if __name__ == "__main__":
    t_http = threading.Thread(target=run_http_server, daemon=True)
    t_http.start()

    t_ping = threading.Thread(target=keep_alive, daemon=True)
    t_ping.start()

    bot.main()
