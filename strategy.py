"""
Turns raw Sleeper data into the "who does this help/hurt" logic you actually
care about: is this MY need, does it hurt my CURRENT OPPONENT, does it hurt a
RECORD NEIGHBOR I'm chasing/being chased by, or is DECLAN (or another fast
mover) about to grab it first.
"""
import config
import sleeper_api
from pushover import PRIORITY_FYI, PRIORITY_WATCH, PRIORITY_URGENT


class LeagueContext:
    """Rebuilt once per polling cycle so it always reflects the latest adds/drops/trades."""

    def __init__(self):
        self.users = sleeper_api.get_league_users(config.LEAGUE_ID)
        self.rosters = sleeper_api.get_league_rosters(config.LEAGUE_ID)
        # Use the league's own 'leg' counter, not the global /state/nfl week --
        # during NFL preseason those two diverge (state/nfl tracks the real-world
        # preseason week, which can be well ahead of your league's actual week 1).
        self.week = sleeper_api.get_current_league_week(config.LEAGUE_ID)

        # user_id -> display_name (Sleeper's login-facing username)
        self.user_id_to_username = {u["user_id"]: u["display_name"] for u in self.users}
        # roster_id -> owner user_id
        self.roster_owner = {r["roster_id"]: r["owner_id"] for r in self.rosters}
        # player_id -> roster_id (only players currently rostered by someone)
        self.player_owner_roster = {}
        for r in self.rosters:
            for pid in (r.get("players") or []):
                self.player_owner_roster[pid] = r["roster_id"]

        # win/loss records, keyed by roster_id
        self.records = {
            r["roster_id"]: (r["settings"].get("wins", 0), r["settings"].get("losses", 0))
            for r in self.rosters
        }

        self.my_user_id = self._find_user_id(config.MY_SLEEPER_USERNAME)
        self.rival_user_id = self._find_user_id(config.PRIORITY_RIVAL_USERNAME)
        self.my_roster_id = self._roster_id_for_user(self.my_user_id)
        self.rival_roster_id = self._roster_id_for_user(self.rival_user_id)

        # Current-week opponent (roster_id), if the schedule is live.
        self.current_opponent_roster_id = self._find_current_opponent()

        # Managers within 1 win of you (excluding yourself) -- your "similar record" list.
        self.record_neighbor_roster_ids = self._find_record_neighbors()

    def _find_user_id(self, username):
        for u in self.users:
            if u["display_name"].lower() == username.lower():
                return u["user_id"]
        return None

    def _roster_id_for_user(self, user_id):
        for rid, owner in self.roster_owner.items():
            if owner == user_id:
                return rid
        return None

    def _find_current_opponent(self):
        if not self.my_roster_id:
            return None
        try:
            matchups = sleeper_api.get_matchups(config.LEAGUE_ID, self.week)
        except Exception:
            return None
        my_matchup_id = None
        for m in matchups:
            if m["roster_id"] == self.my_roster_id:
                my_matchup_id = m["matchup_id"]
                break
        if my_matchup_id is None:
            return None
        for m in matchups:
            if m["matchup_id"] == my_matchup_id and m["roster_id"] != self.my_roster_id:
                return m["roster_id"]
        return None

    def _find_record_neighbors(self):
        if not self.my_roster_id or self.my_roster_id not in self.records:
            return []
        my_wins, my_losses = self.records[self.my_roster_id]
        neighbors = []
        for rid, (w, l) in self.records.items():
            if rid == self.my_roster_id:
                continue
            if abs(w - my_wins) <= 1:
                neighbors.append(rid)
        return neighbors

    def manager_label(self, roster_id):
        owner_id = self.roster_owner.get(roster_id)
        username = self.user_id_to_username.get(owner_id, "unknown")
        return config.MANAGER_NAMES.get(username, username)

    def owner_of_player(self, player_id):
        """Returns roster_id if rostered by someone in the league, else None (free agent)."""
        return self.player_owner_roster.get(player_id)


def classify_player_event(ctx: LeagueContext, player_id, player_name, event_description):
    """
    Decide alert priority + framing for a player-status change (injury,
    inactive, IR, depth-chart signal, trending add spike, etc.)

    Returns (title, message, priority) or None if not actionable.
    """
    owner_roster_id = ctx.owner_of_player(player_id)

    if owner_roster_id is None:
        # Free agent -- this is a pure waiver-wire opportunity.
        title = f"\U0001F7E2 Waiver target: {player_name}"
        message = f"{event_description}\n{player_name} is UNROSTERED in your league -- free agent, first come first served."
        return title, message, PRIORITY_URGENT

    if owner_roster_id == ctx.my_roster_id:
        title = f"\U0001F535 Your player: {player_name}"
        message = f"{event_description}\nThis is on YOUR roster ({config.MANAGER_NAMES.get(config.MY_SLEEPER_USERNAME)}). Check your lineup / IR eligibility."
        return title, message, PRIORITY_URGENT

    owner_label = ctx.manager_label(owner_roster_id)
    tags = []
    if owner_roster_id == ctx.rival_roster_id:
        tags.append("DECLAN-OWNED")
    if owner_roster_id == ctx.current_opponent_roster_id:
        tags.append("YOUR OPPONENT THIS WEEK")
    if owner_roster_id in ctx.record_neighbor_roster_ids:
        tags.append("RECORD NEIGHBOR")

    if not tags:
        # Rostered by someone unremarkable -- lowest priority, informational only.
        title = f"\u26AA Status change: {player_name}"
        message = f"{event_description}\nRostered by {owner_label}. No direct impact on you."
        return title, message, PRIORITY_FYI

    title = f"\U0001F534 {' + '.join(tags)}: {player_name}"
    message = (
        f"{event_description}\n"
        f"Owned by {owner_label}. If this opens a backup/role change, check whether the "
        f"beneficiary is still a free agent -- if so, that's your priority waiver claim."
    )
    return title, message, PRIORITY_URGENT


def classify_free_agent_trend(player_name, trend_count, position, team):
    title = f"\U0001F4C8 Trending add: {player_name}"
    message = (
        f"{player_name} ({position}, {team}) is spiking across Sleeper "
        f"({trend_count} adds recently). If he's still unrostered in your 16-team league, "
        f"this is exactly the kind of surge that means news broke somewhere -- move before "
        f"Declan or your opponent does."
    )
    return title, message, PRIORITY_WATCH


def classify_league_transaction(ctx: LeagueContext, txn):
    """A completed add/drop/trade inside YOUR league -- i.e. a rival just moved."""
    roster_ids = txn.get("roster_ids") or []
    owner_labels = [ctx.manager_label(rid) for rid in roster_ids]
    adds = txn.get("adds") or {}
    drops = txn.get("drops") or {}

    is_rival = ctx.rival_roster_id in roster_ids
    is_opponent = ctx.current_opponent_roster_id in roster_ids
    tag = ""
    priority = PRIORITY_WATCH
    if is_rival:
        tag = "DECLAN MOVED "
        priority = PRIORITY_URGENT
    elif is_opponent:
        tag = "YOUR OPPONENT MOVED "
        priority = PRIORITY_URGENT

    title = f"\U0001F7E1 {tag}Transaction in your league"
    message = f"{', '.join(owner_labels)} -- type: {txn.get('type')}. adds={list(adds.keys())} drops={list(drops.keys())}"
    return title, message, priority
