import os
import threading
import time
import urllib.request
import logging
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
import json

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
                from curl_cffi.requests import AsyncSession
                
                targets = ["chrome124", "safari17_0", "edge101", "tor"]
                for t in targets:
                    try:
                        async with AsyncSession(impersonate=t) as s:
                            r = await s.get(f"https://www.tikwm.com/api/?url={url}&hd=1", timeout=8)
                            results[t] = {"status": r.status_code, "body": r.text[:100]}
                    except Exception as e:
                        results[t] = {"error": str(e)}

                # Also test rapidapi or open tiktok apis
                import httpx
                for endpoint in [
                    f"https://tiktok-download-without-watermark.p.rapidapi.com/analysis?url={url}",
                    f"https://api.vkrdown.com/tiktok?url={url}",
                    f"https://www.tikwm.com/api/?url={url}"
                ]:
                    try:
                        async with httpx.AsyncClient(timeout=8) as cx:
                            r = await cx.get(endpoint, headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"})
                            results[endpoint[:30]] = {"status": r.status_code, "body": r.text[:100]}
                    except Exception as e:
                        results[endpoint[:30]] = {"error": str(e)}

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
