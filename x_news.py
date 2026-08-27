"""
Real-time breaking-news layer using X (Twitter) posts from trusted NFL
insiders. This closes the gap where ESPN's own article can lag the original
break by several minutes -- insiders like Schefter/Rapoport post first,
ESPN writes it up after.

Requires the "x" connector to be connected (OAuth credentials configured by
the user via the X developer console). Calls go through the `xurl` CLI,
which must be invoked with api_credentials=["x"] when run through the
sandbox `bash` tool -- see monitor.py / the hourly cron task text for how
this is wired in.

Cost note: X's API is pay-per-read (roughly $0.005 per post read as of
2026). We keep this cheap by only fetching tweets *since* the last-seen
tweet ID per account (so a quiet account costs ~$0 most polls) and by
tracking a short, curated list of insiders instead of searching broadly.
"""
import json
import subprocess

# Curated list of NFL insiders who consistently break player news first.
# Keep this list short -- every additional account is an extra API read
# every single poll, even when nothing new happened.
TRACKED_ACCOUNTS = [
    "AdamSchefter",   # ESPN
    "RapSheet",       # NFL Network (Ian Rapoport)
    "TomPelissero",   # NFL Network
    "FieldYates",     # ESPN fantasy/NFL
]


def _run_xurl(path):
    """Run xurl against a raw X API path and return parsed JSON, or None on failure."""
    try:
        result = subprocess.run(
            ["xurl", path],
            capture_output=True, text=True, timeout=20, check=True,
        )
        return json.loads(result.stdout)
    except Exception as e:
        print(f"[x_news] request failed for {path}: {e}")
        return None


def get_account_id(username, id_cache):
    """Resolve a username to a numeric X user ID, caching the result."""
    if username in id_cache:
        return id_cache[username]
    data = _run_xurl(f"/2/users/by/username/{username}")
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
    data = _run_xurl(path)
    if not data or "data" not in data:
        return []
    posts = data["data"]
    return [{"id": p["id"], "text": p.get("text", ""), "created_at": p.get("created_at")}
            for p in posts]
