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
                import httpx
                from curl_cffi.requests import AsyncSession
                
                # 1. TikWM GET
                try:
                    async with AsyncSession(impersonate="chrome120") as s:
                        r = await s.get(f"https://www.tikwm.com/api/?url={url}&hd=1", headers={"Referer": "https://www.tikwm.com/"}, timeout=8)
                        results["tikwm_get"] = {"status": r.status_code, "code": r.json().get("code") if r.status_code==200 else r.text[:100]}
                except Exception as e:
                    results["tikwm_get"] = {"error": str(e)}

                # 2. TiklyDown
                try:
                    async with httpx.AsyncClient(timeout=8) as cx:
                        r = await cx.get(f"https://api.tiklydown.eu.org/api/download?url={url}")
                        results["tiklydown"] = {"status": r.status_code, "code": r.json().get("status") if r.status_code==200 else r.text[:100]}
                except Exception as e:
                    results["tiklydown"] = {"error": str(e)}

                # 3. TikTok Official Mobile Feed API
                try:
                    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as cx:
                        # resolve redirect
                        r_red = await cx.get(url, headers={"User-Agent": "Mozilla/5.0"})
                        dest = str(r_red.url)
                        import re
                        m = re.search(r"/(?:video|photo)/(\d+)", dest)
                        if m:
                            vid = m.group(1)
                            mob_url = f"https://api16-normal-c-useast1a.tiktokv.com/aweme/v1/feed/?aweme_id={vid}"
                            r_mob = await cx.get(mob_url, headers={"User-Agent": "com.zhiliaoapp.musically/2022600030 (Linux; U; Android 7.1.2; es_ES; SM-G988N; Build/NRD90M;tt-ok/3.12.13.1)"})
                            data = r_mob.json()
                            aweme = (data.get("aweme_list") or [{}])[0]
                            results["tiktok_mobile"] = {
                                "status": r_mob.status_code,
                                "has_video": bool(aweme.get("video")),
                                "has_images": bool(aweme.get("image_post_info")),
                                "desc": aweme.get("desc", "")[:40]
                            }
                        else:
                            results["tiktok_mobile"] = {"error": f"could not extract vid from {dest}"}
                except Exception as e:
                    results["tiktok_mobile"] = {"error": str(e)}

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
    print(f"Starting health check server on port {port}...", flush=True)
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

    print("Starting Telegram bot in main thread...", flush=True)
    bot.main()
