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
from pushover import send_alert, PRIORITY_FYI, PRIORITY_WATCH, PRIORITY_URGENT
from strategy import (
    LeagueContext,
    classify_player_event,
    classify_free_agent_trend,
    classify_league_transaction,
)


def check_transactions(ctx, st, events):
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
        events.append((title, message, priority))
    st["seen_transaction_ids"] = list(new_seen)[-500:]  # keep the file small


def check_player_statuses(ctx, st, events):
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

        result = classify_player_event(
            ctx, pid, name, "; ".join(changes),
            players=players,
            nfl_team=p.get("team"),
            position=p.get("position"),
            prev_status_pair=(prev["status"], prev["injury_status"]),
            current_status_pair=(current["status"], current["injury_status"]),
        )
        if result:
            title, message, priority = result
            events.append((title, message, priority))

    st["player_status_snapshot"] = snapshot


def check_trending(ctx, st, events):
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
        events.append((title, message, priority))

    st["seen_trending_ids"] = list(seen)[-500:]


def run_once(st):
    ctx = LeagueContext()
    events = []  # list of (title, message, priority) collected this run
    check_transactions(ctx, st, events)
    check_player_statuses(ctx, st, events)
    check_trending(ctx, st, events)
    state_store.save_state(st)

    if not events:
        return

    # FYI-level events (no clear role/waiver impact) are tracked in state for
    # future diffing but deliberately NOT pushed to your phone -- the whole
    # point is fewer, more meaningful alerts focused on rostered-player impact,
    # not a running feed of every minor news timestamp bump.
    actionable = [e for e in events if e[2] > PRIORITY_FYI]
    if not actionable:
        return

    # Send ONE consolidated push per run instead of one per item -- this matters
    # most on the very first run (no prior state), where dozens of items can be
    # "new" simultaneously. Sort so urgent stuff (handcuff opportunities) appears
    # first within the digest.
    order = {PRIORITY_URGENT: 0, PRIORITY_WATCH: 1, PRIORITY_FYI: 2}
    actionable.sort(key=lambda e: order.get(e[2], 1))
    max_priority = max(e[2] for e in actionable)

    if len(actionable) == 1:
        title, message, _ = actionable[0]
        send_alert(title, message, priority=max_priority)
    else:
        title = f"Waiver watch: {len(actionable)} updates"
        message = "\n\n".join(f"\u2022 {t}: {m}" for t, m, _ in actionable)
        # Pushover messages are capped at 1024 chars -- trim gracefully.
        if len(message) > 1000:
            message = message[:997] + "..."
        send_alert(title, message, priority=max_priority)


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
