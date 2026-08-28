# EndZone Intel

Personal-use local app. No hosting — runs on localhost only.

## Stack
- Python + FastAPI backend
- SQLite for local caching
- Vanilla HTML/CSS/JS frontend (dark turf/chalk/amber theme, matches existing draft board artifact)
- espn-api package for ESPN Fantasy data

## Conventions
- Never commit .env (contains ESPN session cookies)
- Keep everything runnable with a single `uvicorn backend.main:app --reload`
- Prefer simple/local over "production-grade" — this is a single-user tool
- Downstream logic should talk to the `LeagueProvider` interface (backend/espn_client.py),
  never to espn-api's raw objects directly — keeps Yahoo/Sleeper support a future addition
  instead of a rewrite
- `backend/sleeper_data.py` is unrelated to that: it's Sleeper's free public
  market-data API (no auth, no league), not a Sleeper `LeagueProvider` - don't
  conflate the two if Sleeper league support is ever added later

## Current phase
Done: Phase 1 (ESPN data mirror), Phase 2 (player analysis / draft board
port), live draft auto-sync (Live Draft Mode), the pick-position draft
simulator, runtime multi-league switching, and the Draft-Day Intel
additions (player news, ESPN-rank ADP fallback, bye-week collision
warnings, weekly opponent info). See docs/superpowers/specs/ for design
docs on each.

The app can now point at a different ESPN league at runtime via the
"League Settings" panel in the topbar (backend/league_settings.py) instead
of hand-editing .env and restarting - this was added specifically because
a real second live league (a work league, on short notice before a draft)
had no way to be used without it. Switching leagues clears cached
roster/standings/draft-state data so the two leagues never mix.

Player data now includes 2026 ADP fields (adp_pick_overall/adp_round/
adp_slot/delta_flag/is_rookie/note) for players covered by the July 2026
4for4 pull, backfilled further by ESPN's own live-synced PPR rank
(`get_espn_rankings`) for players outside that pull. As of August 2026,
`_expected_pick` in analysis.py now checks that live ESPN rank *before*
the frozen July ADP (a live feed is fresher than a two-month-old
snapshot by draft weekend) - the frozen ADP is now just a fallback for
anyone ESPN's rank pull misses. The main Draft Board's rank badge shows
all three signals side by side (hand rank / July ADP / live ESPN rank)
plus a drift indicator when the live rank has moved 15+ picks from the
July snapshot, so staleness is visible instead of silently baked in.

`get_espn_rankings` also now carries each player's live `injuryStatus` in
the same request, merged into the Draft Board/Simulator as
`live_injury_status` and into `analysis.roster_risk_flags` - a real
injury now surfaces even for a player with no hand-set 'injury' flag in
players.py, or one outside the 169-player hand-curated board entirely.
Josh Jacobs's legal-risk note is also now a real 'legal' flag (shows on
the Roster Risk Flags card), not just free text.

`backend/sleeper_data.py` adds a free, no-auth third comparison source -
Sleeper's own platform-wide player popularity rank (`search_rank`) plus
24h trending-add counts - as a stand-in for a paid expert-consensus feed
like FantasyPros. It's manually triggered ("Refresh Sleeper Data" on the
Draft Board, not baked into the ESPN /api/sync loop, per Sleeper's own
guidance not to hit the full player list too often) and purely
informational - shown as a third badge/tooltip line, never fed into
`_expected_pick`'s automatic pick-order logic. **Unverified live**: this
was written from documented Sleeper API knowledge, not tested against
the real API - the sandbox this was built in has no general internet
egress. Click "Refresh Sleeper Data" once locally and check
`GET /api/sleeper/status` shows a real player count before trusting it
on draft day.

Next up: weekly matchup/opponent analysis for start/sit decisions and
transaction-cap tracking (Spec.MD Phase 3), plus trade analytics - both
need their own spec before implementation. Yahoo league support
(a `yahoo_client.py` implementing `LeagueProvider`, per Spec.MD section 7)
is unstarted; it also needs a one-time OAuth app registration on Yahoo's
developer portal, which only the user can do.

Known caveats: `get_espn_rankings`'s single size=300 request is an
untested assumption (see the comment in espn_client.py) - worth
confirming it doesn't truncate against a real league before relying on
it live. `sleeper_data.py` carries the same kind of untested-shape risk
(see above), also worth a manual check before draft day. Also worth
considering: hand-curated tier/rank/flags in players.py are still a
June/July snapshot of judgment calls (not just ADP numbers) - roster
cuts, resolved depth-chart battles, and new season news since then
aren't reflected unless someone edits the file by hand.
