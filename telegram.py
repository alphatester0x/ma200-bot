"""
Telegram helper — kirim pesan dengan rate-limit handling.
"""

import time
from session import SESSION
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from logger import get_logger

log = get_logger("telegram")

_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def send(message: str, delay_after: float = 0.3) -> bool:
    """
    Kirim pesan Telegram.
    delay_after: jeda setelah kirim (detik). Default 0.3s — lebih ringan dari 1s.
    Returns True jika sukses.
    """
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
    }
    try:
        resp = SESSION.post(_URL, json=payload, timeout=10)

        if resp.status_code == 429:
            wait = resp.json().get("parameters", {}).get("retry_after", 5)
            log.warning("Telegram rate-limit, tunggu %ds", wait + 1)
            time.sleep(wait + 1)
            resp = SESSION.post(_URL, json=payload, timeout=10)

        if resp.status_code != 200:
            log.error("Telegram HTTP %s: %s", resp.status_code, resp.text[:100])
            return False

        if delay_after > 0:
            time.sleep(delay_after)
        return True

    except Exception as e:
        log.error("Telegram exception: %s", e)
        return False
