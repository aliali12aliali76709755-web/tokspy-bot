import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
import bot

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
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
    """Pings the public Render URL every 10 minutes through the external router to prevent sleep."""
    url = "https://tokspy-telegram-bot.onrender.com"
    # Wait 2 minutes after startup before first ping
    time.sleep(120)
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TokSpyKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(f"Keep-alive ping: {resp.status}", flush=True)
        except Exception as e:
            print(f"Keep-alive ping notice: {e}", flush=True)
        time.sleep(600)  # every 10 minutes

if __name__ == "__main__":
    # Start HTTP server in daemon thread
    t_http = threading.Thread(target=run_http_server, daemon=True)
    t_http.start()

    # Start self-ping keep-alive in daemon thread
    t_ping = threading.Thread(target=keep_alive, daemon=True)
    t_ping.start()

    # Run Telegram bot in MAIN thread (required for Unix signals)
    print("Starting Telegram bot in main thread...", flush=True)
    bot.main()
