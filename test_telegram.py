"""
Test Telegram bot directly without MT5.
"""
import os
import sys
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv("C:/Users/BASEEL PC/OneDrive/Desktop/تصميم الفا/.env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip().strip('"').strip("'")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip().strip('"').strip("'")

print("=" * 60)
print("TELEGRAM BOT DIAGNOSTIC")
print("=" * 60)
print(f"Token (first 10 chars): {TOKEN[:10]}...")
print(f"Token length: {len(TOKEN)}")
print(f"Chat ID: {CHAT_ID}")

if not TOKEN or not CHAT_ID:
    print("[FAIL] Token or Chat ID missing in .env")
    sys.exit(1)

# 1. Check getMe
print("")
print("[1] Calling getMe to verify token...")
try:
    url = f"https://api.telegram.org/bot{TOKEN}/getMe"
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))
        if data.get("ok"):
            print(f"[OK] Bot verified: {data['result'].get('username')}")
        else:
            print(f"[FAIL] getMe returned not-ok: {data}")
            sys.exit(1)
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8") if e.fp else str(e)
    print(f"[FAIL] HTTP {e.code}: {body}")
    sys.exit(1)
except Exception as e:
    print(f"[FAIL] {type(e).__name__}: {e}")
    sys.exit(1)

# 2. Send test message
print("")
print("[2] Sending test message to chat_id...")
url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {
    "chat_id": CHAT_ID,
    "text": "*TEST FROM ALPHA QUANT*\n\nIf you see this, Telegram integration is working!",
    "parse_mode": "Markdown"
}
try:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))
        if data.get("ok"):
            print(f"[OK] Message sent! message_id: {data['result']['message_id']}")
            print("    CHECK YOUR TELEGRAM NOW!")
        else:
            print(f"[FAIL] sendMessage returned not-ok: {data}")
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8") if e.fp else str(e)
    print(f"[FAIL] HTTP {e.code}: {body}")
except Exception as e:
    print(f"[FAIL] {type(e).__name__}: {e}")

print("")
print("=" * 60)
print("DONE")
print("=" * 60)
