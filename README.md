# Bijan al-Gaib Waiver-Wire Alert Bot

A small Python bot that watches your Sleeper league (**league_id `1389740502990991360`**,
already confirmed live and hardcoded into `config.py`) and pushes phone alerts the
moment something waiver-relevant happens — before you'd normally see it in the app.

## What it watches

1. **Handcuff opportunities (the main signal)** — whenever a rostered player *anywhere
   in your 16-team league* takes a role-ending hit (goes Out/Doubtful/IR/PUP/Inactive),
   the bot looks up his own NFL team's depth chart at that position and tells you by
   name whether the next player in line is still an unrostered free agent in your
   league. This is the "beat everyone to the pickup" case — it doesn't matter who owns
   the injured player, only whether the backup is grabbable.
2. **League transactions** — every add/drop/trade/waiver claim in your 16-team league,
   the second Sleeper processes it. Declan Casey's and your current opponent's moves are
   flagged in red.
3. **Breaking news mentions** — Sleeper's own status field only updates *after* something
   is official, so this closes the gap for rumors and developing stories (suspensions,
   arrests, season-ending injuries, releases, etc.) that break in real reporting first.
   Every ~run, the bot checks ESPN's public NFL news feed for headlines mentioning a
   player rostered anywhere in your league, matched against a role-impact keyword list.
   If a same-position, same-team free agent backup exists, it's named directly — this is
   what would have caught something like a Josh Jacobs suspension rumor the night before
   it became official. Ranked above general trending, since it's a specific, rostered
   player being reported on, not just aggregate add volume.
4. **Site-wide trending adds** — Sleeper's `/players/nfl/trending/add` feed shows which
   players are spiking across *all* Sleeper leagues in the last 24h, filtered to players
   still unrostered in your league. Lowest priority (silent/FYI) since it's the noisiest,
   most general signal — a name spiking site-wide doesn't mean anything happened to your
   league's rosters specifically.

## Alert priorities (what shows up on your phone)

- 🟢 **Urgent** (Pushover high priority): a role just opened up (injury/IR/inactive, *or*
  a breaking-news report like a suspension rumor) and the top healthy backup on that NFL
  team is still a free agent in your league — grab him now. Also: a status change on your
  own roster, or on a player owned by Declan / your current opponent / a manager within
  one win of your record.
- 🟡 **Watch** (normal priority): a role opened up (via status change or breaking news)
  but the top backup is already rostered by someone else (no waiver play, just a
  heads-up), plus general transactions by other managers.
- ⚪ **FYI** (silent, no push): site-wide trending-add noise and status changes with no
  clear role impact or strategic overlap to you.

This matches your priority: you want to know the instant a *rostered* player's injury (or
a credible report of one) creates a grabbable backup, not just that some random player is
trending site-wide. Breaking-news mentions and handcuff opportunities always outrank
general trending in both push priority and where they sort in a digest message. Declan
Casey and your scheduled opponent still get extra tags since they're historically fast
movers, but the handcuff lookup itself runs for all 16 rosters equally.

## Setup — GitHub Actions (recommended, zero building, zero hosting cost)

This repo already has a ready-to-run schedule at `.github/workflows/waiver-watch.yml`.
Once it's on GitHub, GitHub itself checks your league every 5 minutes for free — you
don't build or wire up anything, you only add two secret values one time.

1. **Get a free Pushover account** at [pushover.net](https://pushover.net):
   - Install the Pushover app on your phone and log in.
   - Copy your **User Key** from the pushover.net dashboard.
   - Create an Application (Settings → "Create an Application/API Token"), name it
     something like "Waiver Bot", and copy its **API Token**.
2. **Create a free GitHub account** at [github.com](https://github.com) if you don't
   have one, then create a new repository (top-right "+" → "New repository"). It can
   be **private** — nobody else needs to see it.
3. **Upload this whole folder** into that new repo. Easiest way: on the repo's page,
   click "uploading an existing file", then drag in every file and folder from this
   zip (including the hidden `.github` folder — if your drag-and-drop doesn't pick up
   hidden folders, use GitHub Desktop or `git push` instead, both do include it).
4. **Add your two secrets**: in the repo, go to Settings → Secrets and variables →
   Actions → "New repository secret". Add:
   - `PUSHOVER_APP_TOKEN` = the API Token from step 1
   - `PUSHOVER_USER_KEY` = the User Key from step 1
5. **Enable Actions**: go to the repo's "Actions" tab and click the button to enable
   workflows if prompted. That's it — it now runs automatically every 5 minutes,
   forever, for free, and pushes straight to your phone whenever something actionable
   happens. You can also click "Run workflow" on the Actions tab any time to trigger
   an immediate check.

To change the cadence, edit the `cron: "*/5 * * * *"` line in
`.github/workflows/waiver-watch.yml` (e.g. `*/10 * * * *` for every 10 minutes).
GitHub's practical minimum is about 5 minutes; scheduled workflows can also drift a
few extra minutes when GitHub's runners are busy, but it's still far faster than an
hourly check.

## Alternative: run it yourself instead of GitHub Actions

If you'd rather not use GitHub at all:

1. Install Python 3.10+, then `pip install -r requirements.txt`.
2. Export your Pushover keys as environment variables (or edit the fallback values
   directly in `config.py`):
   ```bash
   export PUSHOVER_APP_TOKEN=your_token
   export PUSHOVER_USER_KEY=your_user_key
   ```
3. Run `python monitor.py --loop` to poll continuously every 60 seconds on a machine
   you leave running (your own always-on VM, a Raspberry Pi, or Replit's "Always On"
   hosted Python runner). Without `--loop`, `python monitor.py` does a single
   check-and-exit, which is what GitHub Actions uses.

## About tracking players' tweets specifically

Real-time keyword/account tweet streaming needs X's paid API tier (their free tier
has no streaming and a very small read quota), so a literal "watch 50 beat writers'
tweets live" bot isn't practical as a free side project. The bot instead uses Sleeper's
own aggregated player-news signal (`news_updated`, `injury_status`, and the trending-add
feed above) as the practical stand-in — it's free, requires no API key, and in practice
reflects breaking beat-writer news within minutes because Sleeper ingests it directly.
If you later want literal tweet monitoring, the cleanest add-on is a paid X API key
plugged into a new `check_twitter()` function alongside the existing checks in
`monitor.py` — the alert routing (`strategy.py`) already supports it, it just needs a
new event source.

## Files

- `.github/workflows/waiver-watch.yml` — the schedule that makes GitHub check your
  league automatically every 5 minutes, for free.
- `config.py` — your league ID, usernames, poll interval; reads Pushover credentials
  from environment variables / repo secrets.
- `sleeper_api.py` — read-only wrapper around the public Sleeper API (no key needed).
- `pushover.py` — sends the phone notification.
- `strategy.py` — decides who each event helps/hurts (you, Declan, your opponent, a
  record neighbor) and how urgent it is.
- `state.py` — remembers what's already been alerted so you don't get duplicates.
- `monitor.py` — the entry point; single check-and-exit by default (what GitHub
  Actions runs), or `--loop` for continuous local polling.

## Fair play note

Everything here reads Sleeper's public, read-only API — the same data every manager can
already see in the app. This just gets it to your phone faster than opening the app, which
is a legitimate speed advantage, not an exploit.
