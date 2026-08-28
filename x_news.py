"""
Real-time breaking-news layer using X (Twitter) posts from trusted NFL
insiders. This closes the gap where ESPN's own article can lag the original
break by several minutes -- insiders like Schefter/Rapoport post first,
ESPN writes it up after.

Two ways this module can authenticate, so the SAME code works in both
places this bot runs:

1. GitHub Actions (this repo's 5-minute schedule) -- set the X_BEARER_TOKEN
   environment variable (a GitHub Actions repo secret) to your own X API
   App-only Bearer Token (from your X developer app's "Keys and Tokens" tab
   -- a different field than the OAuth 2.0 Client ID/Secret used for the
   Perplexity connector). This is the fast path: checked every ~5 minutes.
2. Perplexity-managed cron -- falls back to the `xurl` CLI (Perplexity's
   own X connector, via api_credentials=["x"]) if X_BEARER_TOKEN isn't set.
   This only checks hourly, so it's a slower backup path, not the primary
   one -- kept as a redundant safety net in case the fast path has an outage.

Cost note: X's API is pay-per-read (roughly $0.005 per post read as of
2026). We keep this cheap by only fetching tweets *since* the last-seen
tweet ID per account (so a quiet account costs ~$0 most polls) and by
tracking a short, curated list of insiders instead of searching broadly.
"""
import json
import os
import subprocess

import requests

# Curated list of NFL insiders who consistently break player news first.
# Keep this list short -- every additional account is an extra API read
# every single poll, even when nothing new happened.
TRACKED_ACCOUNTS = [
    "AdamSchefter",   # ESPN
    "RapSheet",       # NFL Network (Ian Rapoport)
    "TomPelissero",   # NFL Network
    "FieldYates",     # ESPN fantasy/NFL
    "MikeGarafolo",   # NFL Network -- routinely ranked alongside Rapoport/Schefter/Pelissero
]

X_API_BASE = "https://api.twitter.com"  # paths below include the /2 prefix themselves


def _bearer_token():
    return os.environ.get("X_BEARER_TOKEN")


def _request_via_bearer(path):
    """Direct HTTPS call to the X API using an App-only Bearer token."""
    token = _bearer_token()
    if not token:
        return None
    url = f"{X_API_BASE}{path}"
    try:
        resp = requests.get(
            url, headers={"Authorization": f"Bearer {token}"}, timeout=20,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[x_news] bearer request failed for {path}: {e}")
        return None


def _request_via_xurl(path):
    """Fallback: Perplexity's own X connector via the xurl CLI. Only
    reachable when this code runs inside a Perplexity-managed cron with
    api_credentials=["x"] -- fails soft (returns None) everywhere else,
    e.g. on a bare GitHub Actions runner where `xurl` doesn't exist."""
    try:
        result = subprocess.run(
            ["xurl", path],
            capture_output=True, text=True, timeout=20, check=True,
        )
        return json.loads(result.stdout)
    except Exception as e:
        print(f"[x_news] xurl request failed for {path}: {e}")
        return None


def _get(path):
    """Try the fast Bearer-token path first (GitHub Actions), then fall
    back to xurl (Perplexity cron). Returns parsed JSON dict, or None if
    neither path is available/working."""
    if _bearer_token():
        return _request_via_bearer(path)
    return _request_via_xurl(path)


def get_account_id(username, id_cache):
    """Resolve a username to a numeric X user ID, caching the result."""
    if username in id_cache:
        return id_cache[username]
    data = _get(f"/2/users/by/username/{username}")
    if not data or "data" not in data:
        return None
    user_id = data["data"]["id"]
    id_cache[username] = user_id
    return user_id


def get_new_posts(username, user_id, since_id):
    """
    Fetch posts newer than since_id (exclusive) for a given account.
    Returns a list of {"id": ..., "text": ..., "created_at": ...} dicts,
    newest first. Returns [] if nothing new or on failure -- never raises,
    so one flaky account doesn't break the whole run.
    """
    path = f"/2/users/{user_id}/tweets?max_results=10&tweet.fields=created_at"
    if since_id:
        path += f"&since_id={since_id}"
    data = _get(path)
    if not data or "data" not in data:
        return []
    posts = data["data"]
    return [{"id": p["id"], "text": p.get("text", ""), "created_at": p.get("created_at")}
            for p in posts]
