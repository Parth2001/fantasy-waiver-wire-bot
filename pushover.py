"""
Send push notifications to your phone via Pushover.
https://pushover.net/api
"""
import requests
import config

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"

# Pushover priority levels:
#  -1 = quiet notification (no sound)
#   0 = normal
#   1 = high priority (bypasses quiet hours)
#   2 = emergency (repeats until acknowledged -- use sparingly)
PRIORITY_FYI = -1
PRIORITY_WATCH = 0
PRIORITY_URGENT = 1


def send_alert(title, message, priority=PRIORITY_WATCH, url=None, url_title=None):
    if "PUT_YOUR" in config.PUSHOVER_APP_TOKEN or "PUT_YOUR" in config.PUSHOVER_USER_KEY:
        print(f"[DRY RUN -- add your Pushover keys to config.py] {title}: {message}")
        return

    payload = {
        "token": config.PUSHOVER_APP_TOKEN,
        "user": config.PUSHOVER_USER_KEY,
        "title": title,
        "message": message,
        "priority": priority,
    }
    if priority == 2:
        # Emergency priority requires retry/expire params.
        payload["retry"] = 60
        payload["expire"] = 3600
    if url:
        payload["url"] = url
        payload["url_title"] = url_title or "Open Sleeper"

    resp = requests.post(PUSHOVER_URL, data=payload, timeout=15)
    resp.raise_for_status()
