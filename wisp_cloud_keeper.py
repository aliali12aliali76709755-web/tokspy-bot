"""
24/7 Cloud Watchdog Script for GitHub Actions / Cloud Cron.
Runs periodically in the cloud without requiring any local machine to be turned on.
Checks bot health, renews WispByte captcha timer, and restarts the server if offline.
"""
import urllib.request
import json
import os
import sys

SERVER_ID = "5cd53697"
HEALTH_URL = "http://78.154.103.52:11648/health"
WISP_COOKIE = os.environ.get("WISP_COOKIE", "s%3A4Fekw87o3uJCaZATHsCLVrczXshhM2uO.vrpczQkuCtyxuAa3WxtP0gJAWCS14d7zfBY8gV%2BYN%2F0")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://wispbyte.com/client/servers/5cd53697/console",
    "Origin": "https://wispbyte.com",
    "Cookie": f"connect.sid={WISP_COOKIE}",
    "Content-Type": "application/json"
}

def renew_captcha():
    print("[Keeper] Renewing WispByte captcha...")
    try:
        req = urllib.request.Request(
            "https://wispbyte.com/client/api/server/start-captcha/rewarded",
            data=b"{}",
            headers=HEADERS
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode('utf-8')
            print(f"[Keeper] Captcha response: {resp.status} {body}")
            return True
    except Exception as e:
        print(f"[Keeper] Captcha renew error: {e}")
        return False

def check_health():
    print(f"[Keeper] Checking bot health at {HEALTH_URL}...")
    try:
        req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "TokSpyCloudKeeper/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[Keeper] Health check status: {resp.status}")
            return resp.status == 200
    except Exception as e:
        print(f"[Keeper] Health check error: {e}")
        return False

def start_server():
    print(f"[Keeper] Sending START command to server {SERVER_ID}...")
    try:
        data = json.dumps({"serverId": SERVER_ID}).encode('utf-8')
        req = urllib.request.Request(
            "https://wispbyte.com/client/api/server/start",
            data=data,
            headers=HEADERS
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode('utf-8')
            print(f"[Keeper] Start server response: {resp.status} {body}")
            return True
    except Exception as e:
        print(f"[Keeper] Start server error: {e}")
        return False

def main():
    print("=== TokSpy Cloud Keeper Starting ===")
    renew_captcha()
    is_up = check_health()
    if is_up:
        print("[Keeper] Bot is HEALTHY and running properly!")
    else:
        print("[Keeper] Bot is DOWN! Attempting to revive...")
        start_server()
        print("[Keeper] Revive command issued successfully.")
    print("=== TokSpy Cloud Keeper Completed ===")

if __name__ == "__main__":
    main()
