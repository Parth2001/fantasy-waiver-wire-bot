"""
Thin wrapper around the public, read-only Sleeper API.
No API key is required. Sleeper asks that you stay well under 1000
requests/minute -- this bot polls once a minute by default, so you're
nowhere close to that limit.
Docs: https://docs.sleeper.com/
"""
import json
import os
import time
import requests

BASE = "https://api.sleeper.app/v1"
PLAYERS_CACHE_FILE = "players_cache.json"


def _get(url, params=None):
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def get_nfl_state():
    """Current NFL week/season info. NOTE: during preseason this 'week' field
    reflects the real-world preseason week, NOT your league's fantasy week --
    use get_current_league_week() below instead for anything league-related."""
    return _get(f"{BASE}/state/nfl")


def get_league_info(league_id):
    """Full league object, including settings.leg -- the league's own current
    fantasy week counter."""
    return _get(f"{BASE}/league/{league_id}")


def get_current_league_week(league_id):
    """The correct 'current week' to use for matchups/transactions endpoints.
    Sleeper's global /state/nfl week can be ahead of your league's actual
    week during NFL preseason (e.g. state/nfl says preseason week 3 while
    your league's real week 1 hasn't started). settings.leg is the league's
    own authoritative week counter and should always be preferred."""
    info = get_league_info(league_id)
    settings = info.get("settings", {}) or {}
    leg = settings.get("leg")
    if leg:
        return leg
    return settings.get("start_week") or 1


def get_league_users(league_id):
    """List of managers in the league (user_id, display_name, team name)."""
    return _get(f"{BASE}/league/{league_id}/users")


def get_league_rosters(league_id):
    """List of rosters: roster_id, owner_id, players[], starters[], settings (wins/losses)."""
    return _get(f"{BASE}/league/{league_id}/rosters")


def get_transactions(league_id, week):
    """Waiver claims, free agent adds/drops, and trades processed for a given week."""
    return _get(f"{BASE}/league/{league_id}/transactions/{week}")


def get_matchups(league_id, week):
    """Head-to-head groupings for a given week (roster_id -> matchup_id)."""
    return _get(f"{BASE}/league/{league_id}/matchups/{week}")


def get_trending_players(add_or_drop="add", lookback_hours=24, limit=50):
    """
    League-agnostic, site-wide signal: which NFL players are being added/dropped
    fastest across all of Sleeper right now. Useful as an early-warning radar --
    a spike here often means news broke (injury, role change, depth-chart move)
    before your own 16-man league has reacted.
    """
    return _get(
        f"{BASE}/players/nfl/trending/{add_or_drop}",
        params={"lookback_hours": lookback_hours, "limit": limit},
    )


def get_all_players(force_refresh=False, max_age_hours=12, state=None):
    """
    Full NFL player dictionary (player_id -> {full_name, team, position,
    status, injury_status, news_updated, ...}). This is a big file (~5-8MB),
    so it is cached locally and only re-downloaded every max_age_hours.

    IMPORTANT: staleness is tracked via a timestamp persisted in state.json
    (state["players_cache_fetched_at"]), NOT via the cache file's filesystem
    mtime. On GitHub Actions, actions/checkout resets every file's mtime to
    the moment of checkout on every single run -- so an mtime-based check
    always sees the file as "just created" and never re-fetches, silently
    freezing all injury/status data at whatever was last fetched. (This bot
    ran for 2+ weeks on a cache from Aug 27 before this was caught.) A
    caller that doesn't pass `state` falls back to the old mtime check for
    non-bot local usage, but the bot itself must always pass state.
    """
    if state is not None:
        fetched_at = state.get("players_cache_fetched_at", 0)
        age_hours = (time.time() - fetched_at) / 3600
        if not force_refresh and age_hours < max_age_hours and os.path.exists(PLAYERS_CACHE_FILE):
            with open(PLAYERS_CACHE_FILE, "r") as f:
                return json.load(f)

        data = _get(f"{BASE}/players/nfl")
        with open(PLAYERS_CACHE_FILE, "w") as f:
            json.dump(data, f)
        state["players_cache_fetched_at"] = time.time()
        return data

    # Legacy path (no state passed) -- kept only for ad-hoc local scripts.
    if not force_refresh and os.path.exists(PLAYERS_CACHE_FILE):
        age_hours = (time.time() - os.path.getmtime(PLAYERS_CACHE_FILE)) / 3600
        if age_hours < max_age_hours:
            with open(PLAYERS_CACHE_FILE, "r") as f:
                return json.load(f)

    data = _get(f"{BASE}/players/nfl")
    with open(PLAYERS_CACHE_FILE, "w") as f:
        json.dump(data, f)
    return data
