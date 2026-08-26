"""
Configuration for the fantasy waiver-wire alert bot.

Everything about YOUR league is already filled in below (confirmed live
against the Sleeper API on 2026-08-26). Pushover credentials are read from
environment variables (PUSHOVER_APP_TOKEN / PUSHOVER_USER_KEY) so you never
have to put secrets in this file -- when running on GitHub Actions, set them
as repo secrets; when running locally, export them in your shell first.
"""
import os

# ---------------------------------------------------------------------------
# Sleeper league identity (already resolved from your draft board link:
# https://sleeper.app/draft/nfl/1389740502990991361 -> league_id below)
# ---------------------------------------------------------------------------
LEAGUE_ID = "1389740502990991360"

# Your Sleeper username -> used to find your own roster automatically.
MY_SLEEPER_USERNAME = "Parth2001"

# The manager you most want to beat to the waiver wire (per your notes:
# he grabbed an RB ahead of the Josh Jacobs suspension news before most
# of the league reacted).
PRIORITY_RIVAL_USERNAME = "declancasey7"  # Declan Casey

# ---------------------------------------------------------------------------
# Pushover credentials -- https://pushover.net
# 1. Create a free account, install the Pushover app on your phone.
# 2. Copy your "User Key" from the pushover.net dashboard.
# 3. Create an Application (Settings > API Token/Keys on pushover.net),
#    name it e.g. "Waiver Bot", copy its API Token.
# ---------------------------------------------------------------------------
PUSHOVER_APP_TOKEN = os.environ.get("PUSHOVER_APP_TOKEN", "PUT_YOUR_PUSHOVER_APP_TOKEN_HERE")
PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY", "PUT_YOUR_PUSHOVER_USER_KEY_HERE")

# ---------------------------------------------------------------------------
# Polling behavior
# ---------------------------------------------------------------------------
POLL_INTERVAL_SECONDS = 60          # how often to check Sleeper for changes
PLAYER_DB_REFRESH_HOURS = 12        # Sleeper asks you not to hit /players/nfl more than once per few hours
STATE_FILE = "state.json"           # local memory of what's already been alerted

# Manual real-name overlay (Sleeper only exposes usernames/team names).
# roster_id is assigned by Sleeper and stays fixed for the season.
MANAGER_NAMES = {
    "hnw01": "Harrison",
    "grantsmith12": "Gent (Grant Smith)",
    "Parth2001": "Parth (you)",
    "oldryan": "Ryan Old",
    "declancasey7": "Declan Casey",
    "ompatel": "Om",
    "Jasonlacks": "Jason",
    "masonz": "Mason",
    "benhenderson10": "Ben Henderson",
    "taggert17": "Tag",
    "claw125": "Carter",
    "DeclanBlodgett": "Declan B",
    "Rman9": "Ryan Manley",
    "BiGGGGEthaplug": "Ethan",
    "KaranKP": "Karan",
    "JackLamoree": "Jack",
}
