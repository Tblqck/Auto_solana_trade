import os
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

_BOT_TOKEN = os.getenv("Trade_crpyt", "")
_CHAT_ID   = "7416057134"


def send(text: str) -> bool:
    """Post a message to the configured Telegram chat. Silent on failure."""
    if not _BOT_TOKEN:
        print("[Notify] Telegram not configured (missing Trade_crpyt)")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
            json={"chat_id": _CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if not resp.ok:
            print(f"[Notify] Send failed: {resp.status_code} {resp.text[:100]}")
            return False
        return True
    except Exception as e:
        print(f"[Notify] Error: {e}")
        return False
