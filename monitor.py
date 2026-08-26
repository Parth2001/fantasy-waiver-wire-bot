"""
Run with:  python monitor.py            (single check-and-exit -- used by
                                          GitHub Actions, which re-invokes
                                          this on its own schedule)
       or: python monitor.py --loop     (continuous local polling loop,
                                          if you'd rather run this on your
                                          own always-on machine instead)

Each run checks, for your league:
  1. New transactions (adds/drops/trades/waiver claims) by ANY manager --
     flags Declan or your current opponent specially, but fires for everyone.
  2. Player status changes (injury_status, active/inactive, IR, news_updated
     timestamp bump) for every player rostered anywhere in your 16-team league.
  3. Site-wide trending adds on Sleeper -- an early-warning radar for news
     that hasn't hit your league's chat yet, filtered to free agents in your league.

Every actionable event gets pushed straight to your phone via Pushover.
"""
import sys
import time
import traceback

import config
import sleeper_api
import state as state_store
from pushover import send_alert
from strategy import (
    LeagueContext,
    classify_player_event,
    classify_free_agent_trend,
    classify_league_transaction,
)


def check_transactions(ctx, st):
    new_seen = set(st["seen_transaction_ids"])
    try:
        txns = sleeper_api.get_transactions(config.LEAGUE_ID, ctx.week)
    except Exception as e:
        print(f"[transactions] fetch failed: {e}")
        return
    for txn in txns:
        txn_id = txn.get("transaction_id")
        if not txn_id or txn_id in new_seen:
            continue
        if txn.get("status") != "complete":
            continue
        new_seen.add(txn_id)
        title, message, priority = classify_league_transaction(ctx, txn)
        send_alert(title, message, priority=priority)
    st["seen_transaction_ids"] = list(new_seen)[-500:]  # keep the file small


def check_player_statuses(ctx, st):
    players = sleeper_api.get_all_players(max_age_hours=config.PLAYER_DB_REFRESH_HOURS)
    snapshot = st["player_status_snapshot"]
    rostered_ids = set(ctx.player_owner_roster.keys())

    for pid in rostered_ids:
        p = players.get(pid)
        if not p:
            continue
        current = {
            "status": p.get("status"),
            "injury_status": p.get("injury_status"),
            "news_updated": p.get("news_updated"),
        }
        prev = snapshot.get(pid)
        snapshot[pid] = current
        if prev is None:
            continue  # first time seeing this player, nothing to diff against
        if current == prev:
            continue

        name = p.get("full_name") or f"{p.get('first_name','')} {p.get('last_name','')}".strip()
        changes = []
        if current["status"] != prev["status"]:
            changes.append(f"status {prev['status']} -> {current['status']}")
        if current["injury_status"] != prev["injury_status"]:
            changes.append(f"injury {prev['injury_status']} -> {current['injury_status']}")
        if current["news_updated"] != prev["news_updated"]:
            changes.append("new player-news update posted")
        if not changes:
            continue

        result = classify_player_event(ctx, pid, name, "; ".join(changes))
        if result:
            title, message, priority = result
            send_alert(title, message, priority=priority)

    st["player_status_snapshot"] = snapshot


def check_trending(ctx, st):
    try:
        trending = sleeper_api.get_trending_players(add_or_drop="add", lookback_hours=24, limit=25)
    except Exception as e:
        print(f"[trending] fetch failed: {e}")
        return
    players = sleeper_api.get_all_players(max_age_hours=config.PLAYER_DB_REFRESH_HOURS)
    seen = set(st["seen_trending_ids"])

    for entry in trending:
        pid = entry.get("player_id")
        if not pid or pid in seen:
            continue
        # Only alert if this player is a free agent in YOUR league -- otherwise it's noise.
        if ctx.owner_of_player(pid) is not None:
            continue
        seen.add(pid)
        p = players.get(pid, {})
        name = p.get("full_name") or pid
        title, message, priority = classify_free_agent_trend(
            name, entry.get("count", 0), p.get("position", "?"), p.get("team", "FA")
        )
        send_alert(title, message, priority=priority)

    st["seen_trending_ids"] = list(seen)[-500:]


def run_once(st):
    ctx = LeagueContext()
    check_transactions(ctx, st)
    check_player_statuses(ctx, st)
    check_trending(ctx, st)
    state_store.save_state(st)


def main():
    loop_mode = "--loop" in sys.argv
    st = state_store.load_state()

    if not loop_mode:
        # Single check-and-exit -- this is the mode GitHub Actions uses.
        # The scheduled workflow re-invokes this script fresh on its own cadence.
        try:
            run_once(st)
        except Exception:
            print("Unhandled error this run:")
            traceback.print_exc()
            sys.exit(1)
        return

    print(f"Starting waiver-wire bot for league {config.LEAGUE_ID}. "
          f"Polling every {config.POLL_INTERVAL_SECONDS}s. Ctrl+C to stop.")
    while True:
        try:
            run_once(st)
        except Exception:
            print("Unhandled error this cycle -- will retry next poll:")
            traceback.print_exc()
        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
