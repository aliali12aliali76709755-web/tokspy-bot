import os
import threading
import traceback
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

LAST_ERROR = "No errors. Bot is running."
BOT_STATUS = "initializing"

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        res = {
            "status": "ok",
            "bot": "TokSpy",
            "bot_status": BOT_STATUS,
            "last_error": LAST_ERROR
        }
        self.wfile.write(json.dumps(res, ensure_ascii=False).encode('utf-8'))

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

def start_bot():
    global LAST_ERROR, BOT_STATUS
    while True:
        try:
            print("Importing and starting bot...", flush=True)
            BOT_STATUS = "starting"
            import bot
            BOT_STATUS = "running"
            bot.main()
        except Exception as e:
            BOT_STATUS = "error"
            LAST_ERROR = traceback.format_exc()
            print("BOT CRASHED:\n", LAST_ERROR, flush=True)
            print("Retrying in 10 seconds...", flush=True)
            time.sleep(10)

if __name__ == "__main__":
    t_bot = threading.Thread(target=start_bot, daemon=True)
    t_bot.start()

    # Keep HTTP server in main thread
    run_http_server()
