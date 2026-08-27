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


NEGATIVE_STATUSES = {"Out", "Doubtful", "IR", "PUP", "NA", "Suspended", "COV", "Injured Reserve"}
BACKUP_RELEVANT_POSITIONS = {"QB", "RB", "WR", "TE"}


def _is_role_opening_change(event_description, prev_status_pair, current_status_pair):
    """Heuristic: did this change plausibly knock the player OUT of their role
    (as opposed to a minor news bump or an improvement, e.g. Questionable->Active)?"""
    prev_status, prev_injury = prev_status_pair
    cur_status, cur_injury = current_status_pair
    if cur_injury in NEGATIVE_STATUSES and cur_injury != prev_injury:
        return True
    if cur_status in ("Inactive", "Injured Reserve", "PUP") and cur_status != prev_status:
        return True
    return False


def find_position_backups(players, ctx, nfl_team, position, injured_player_id, limit=2):
    """Same NFL team + same position, healthy, excluding the injured player --
    sorted by depth chart order (or search rank if depth chart data is missing).
    This is the actual 'who benefits' lookup, so alerts can name the handcuff
    instead of just saying 'check for a beneficiary'."""
    if not nfl_team or position not in BACKUP_RELEVANT_POSITIONS:
        return []
    candidates = []
    for pid, p in players.items():
        if pid == injured_player_id:
            continue
        if p.get("team") != nfl_team or p.get("position") != position:
            continue
        if p.get("status") in ("Inactive", "Injured Reserve", "PUP"):
            continue  # skip other guys who are themselves out
        candidates.append((pid, p))

    def sort_key(item):
        _, p = item
        dco = p.get("depth_chart_order")
        if dco is not None:
            return (0, dco)
        return (1, p.get("search_rank") or 9999)

    candidates.sort(key=sort_key)

    results = []
    for pid, p in candidates[:limit]:
        owner_rid = ctx.owner_of_player(pid)
        results.append({
            "player_id": pid,
            "name": p.get("full_name") or pid,
            "free_agent": owner_rid is None,
            "owner_label": ctx.manager_label(owner_rid) if owner_rid is not None else None,
        })
    return results


def classify_player_event(ctx: LeagueContext, player_id, player_name, event_description,
                           players=None, nfl_team=None, position=None,
                           prev_status_pair=None, current_status_pair=None):
    """
    Decide alert priority + framing for a player-status change (injury,
    inactive, IR, depth-chart signal, trending add spike, etc.)

    The main goal here is NOT "a player somewhere changed status" -- it's
    "does this open a role that has a still-unrostered beneficiary you can
    grab before anyone else." That backup lookup runs whenever we have the
    player pool available and the change looks role-opening.

    Returns (title, message, priority) or None if not actionable.
    """
    owner_roster_id = ctx.owner_of_player(player_id)
    role_opening = bool(
        players is not None and prev_status_pair and current_status_pair
        and _is_role_opening_change(event_description, prev_status_pair, current_status_pair)
    )

    backups = []
    if role_opening and players is not None:
        backups = find_position_backups(players, ctx, nfl_team, position, player_id)

    free_agent_backup = next((b for b in backups if b["free_agent"]), None)

    owner_label = ctx.manager_label(owner_roster_id) if owner_roster_id is not None else "nobody (free agent)"

    # --- Case 1: a role just opened AND the top healthy backup is unrostered. ---
    # This is the headline alert type: pick him up before anyone else does.
    if role_opening and free_agent_backup:
        title = f"\U0001F7E2 Handcuff opportunity: {free_agent_backup['name']}"
        message = (
            f"{player_name} ({event_description}), owned by {owner_label}, just opened up "
            f"the {position} role on {nfl_team}.\n"
            f"{free_agent_backup['name']} is next in line by depth chart and is UNROSTERED "
            f"in your league -- grab him before Declan or anyone else does."
        )
        return title, message, PRIORITY_URGENT

    # --- Case 2: role opened, but the top backup is already rostered by someone. ---
    if role_opening and backups and not free_agent_backup:
        top = backups[0]
        title = f"\U0001F7E1 Role opening, backup already owned: {player_name}"
        message = (
            f"{player_name} ({event_description}), owned by {owner_label}, just opened up "
            f"the {position} role on {nfl_team}.\n"
            f"Next in line is {top['name']}, but he's already rostered by {top['owner_label']} -- "
            f"no waiver opportunity here, just watch for a trade angle."
        )
        return title, message, PRIORITY_WATCH

    if owner_roster_id is None:
        # Free agent -- this is a pure waiver-wire opportunity on the player himself.
        title = f"\U0001F7E2 Waiver target: {player_name}"
        message = f"{event_description}\n{player_name} is UNROSTERED in your league -- free agent, first come first served."
        return title, message, PRIORITY_URGENT

    if owner_roster_id == ctx.my_roster_id:
        title = f"\U0001F535 Your player: {player_name}"
        message = f"{event_description}\nThis is on YOUR roster ({config.MANAGER_NAMES.get(config.MY_SLEEPER_USERNAME)}). Check your lineup / IR eligibility."
        return title, message, PRIORITY_URGENT

    tags = []
    if owner_roster_id == ctx.rival_roster_id:
        tags.append("DECLAN-OWNED")
    if owner_roster_id == ctx.current_opponent_roster_id:
        tags.append("YOUR OPPONENT THIS WEEK")
    if owner_roster_id in ctx.record_neighbor_roster_ids:
        tags.append("RECORD NEIGHBOR")

    if not tags and not role_opening:
        # Minor/unremarkable change (e.g. a news bump with no clear role impact)
        # on someone else's roster -- lowest priority, informational only.
        title = f"\u26AA Status change: {player_name}"
        message = f"{event_description}\nRostered by {owner_label}. No direct impact on you."
        return title, message, PRIORITY_FYI

    tag_str = f"{' + '.join(tags)}: " if tags else ""
    title = f"\U0001F534 {tag_str}{player_name}"
    message = (
        f"{event_description}\n"
        f"Owned by {owner_label}. No clear unrostered beneficiary found yet -- keep an eye on the depth chart."
    )
    return title, message, PRIORITY_URGENT if tags else PRIORITY_WATCH


_NAME_SUFFIXES = (" jr", " sr", " ii", " iii", " iv", " v")


def normalize_player_name(name):
    """Sleeper and ESPN don't always agree on suffixes (Sleeper: 'Calvin
    Austin', ESPN: 'Calvin Austin III') -- strip trailing Jr/Sr/II/III/IV/V
    and punctuation so name-matching across the two sources actually works."""
    n = (name or "").lower().strip().replace(".", "").replace(",", "")
    for suffix in _NAME_SUFFIXES:
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
            break
    return n


ROLE_IMPACT_KEYWORDS = [
    "suspend", "suspension", "arrest", "domestic", "injured reserve", " ir ",
    "tore", "torn", "surgery", "out for the season", "out for the year",
    "ruled out", "waived", "released", "carted off", "will miss",
    "placed on injured", "achilles", "concussion protocol", "done for the year",
    # Added after missing the Josh Jacobs misdemeanor-charges story (ESPN's own
    # headline said "charged with misdemeanor battery and misdemeanor criminal
    # damage to property" -- none of the words above matched it):
    "charged", "misdemeanor", "felony", "battery", "criminal", "indicted",
    "citation", "cited by police", "legal trouble", "investigation",
]


def headline_matches_role_impact(text):
    text = f" {text.lower()} "
    return any(kw in text for kw in ROLE_IMPACT_KEYWORDS)


def classify_breaking_news(ctx: LeagueContext, players, player_id, player_name,
                            headline, article_url):
    """
    A player mentioned in real NFL news copy (not yet reflected in Sleeper's
    structured status field) alongside a role-impact keyword -- e.g. a
    suspension-is-coming report, before the league office makes it official.
    This is the exact "rumor should still alert me" gap a pure status-diff
    approach misses.
    """
    p = players.get(player_id, {})
    nfl_team = p.get("team")
    position = p.get("position")
    owner_roster_id = ctx.owner_of_player(player_id)
    owner_label = ctx.manager_label(owner_roster_id) if owner_roster_id is not None else "nobody (free agent)"

    backups = find_position_backups(players, ctx, nfl_team, position, player_id)
    free_agent_backup = next((b for b in backups if b["free_agent"]), None)

    if free_agent_backup:
        title = f"\U0001F7E2 Breaking news handcuff: {free_agent_backup['name']}"
        message = (
            f"\U0001F4F0 {headline}\n"
            f"{player_name} (owned by {owner_label}) is named in breaking news that could open "
            f"up the {position} role on {nfl_team} -- not yet reflected in official status, "
            f"but {free_agent_backup['name']} is next in line and still UNROSTERED. "
            f"Grab him now before the news fully breaks league-wide.\n{article_url}"
        )
        return title, message, PRIORITY_URGENT

    title = f"\U0001F4F0 Breaking news: {player_name}"
    message = (
        f"{headline}\n"
        f"{player_name} (owned by {owner_label}) is named in a report that could affect his role. "
        f"No clear unrostered beneficiary yet -- worth a quick look at his team's depth chart.\n{article_url}"
    )
    return title, message, PRIORITY_WATCH


def classify_free_agent_trend(player_name, trend_count, position, team):
    # Lower priority than a rostered-player-impact alert (the "handcuff opportunity"
    # cases above) -- site-wide trending is a useful early-warning radar but a much
    # noisier signal than "a specific rostered guy on his team just got hurt."
    title = f"\U0001F4C8 Trending add: {player_name}"
    message = (
        f"{player_name} ({position}, {team}) is spiking across Sleeper "
        f"({trend_count} adds recently). If he's still unrostered in your 16-team league, "
        f"this is exactly the kind of surge that means news broke somewhere -- move before "
        f"Declan or your opponent does."
    )
    return title, message, PRIORITY_FYI


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
