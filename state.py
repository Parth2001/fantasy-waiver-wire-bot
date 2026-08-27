"""Tiny local JSON store so the bot remembers what it already alerted you
about between polling cycles (and across restarts)."""
import json
import os
import config

DEFAULTS = {
    "seen_transaction_ids": [],
    "player_status_snapshot": {},   # player_id -> {"status": ..., "injury_status": ..., "news_updated": ...}
    "seen_trending_ids": [],
    "seen_news_ids": [],   # ESPN article ids already checked, for breaking-news mentions
    "x_account_ids": {},   # username -> numeric X user ID (cached to avoid repeat lookups)
    "x_last_seen_ids": {},  # username -> newest tweet ID already processed from that account
}


def load_state():
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE, "r") as f:
            data = json.load(f)
        for k, v in DEFAULTS.items():
            data.setdefault(k, v)
        return data
    return json.loads(json.dumps(DEFAULTS))


def save_state(state):
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
