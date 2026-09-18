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
            async def run_dbg():
                results = {}
                import httpx
                
                # Test SSSTik
                try:
                    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as cx:
                        r_page = await cx.get("https://ssstik.io/en", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                        tt_m = re.search(r'data-tt="([^"]+)"', r_page.text)
                        tt = tt_m.group(1) if tt_m else "0"
                        r_post = await cx.post(
                            "https://ssstik.io/abc?url=dl",
                            data={"id": url, "locale": "en", "tt": tt},
                            headers={"hx-request": "true", "hx-target": "target", "hx-current-url": "https://ssstik.io/en", "User-Agent": "Mozilla/5.0"}
                        )
                        links = re.findall(r'href="([^"]+)"', r_post.text)
                        results["ssstik"] = {
                            "status": r_post.status_code,
                            "links_count": len(links),
                            "first_link": links[0][:60] if links else None
                        }
                except Exception as e:
                    results["ssstik"] = {"error": str(e)}

                return results

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
