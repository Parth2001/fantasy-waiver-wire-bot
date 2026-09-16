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
    "players_cache_fetched_at": 0,  # epoch seconds of last real players_cache.json refresh
    # player_id -> {"ts": epoch_seconds, "status_pair": [status, injury_status]} for the
    # most recent alert sent about that player, from ANY detection path (structured status
    # diff, ESPN breaking news, or X breaking news). Lets the three independent checks avoid
    # re-alerting on the exact same underlying fact (added 2026-09-16 -- Dylan Sampson's IR
    # move fired once via breaking news and again via the structured diff within minutes).
    "alerted_players_recent": {},
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
