import os
import threading
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

if __name__ == "__main__":
    # Start HTTP server in daemon thread
    t = threading.Thread(target=run_http_server, daemon=True)
    t.start()

    # Run Telegram bot in MAIN thread (required for Unix signals)
    print("Starting Telegram bot in main thread...", flush=True)
    bot.main()
