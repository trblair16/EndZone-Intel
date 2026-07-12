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

## Current phase
Done: Phase 1 (ESPN data mirror), Phase 2 (player analysis / draft board
port), live draft auto-sync (Live Draft Mode), and the pick-position draft
simulator. See docs/superpowers/specs/ for design docs on each.

Player data now includes 2026 ADP fields (adp_pick_overall/adp_round/
adp_slot/delta_flag/is_rookie/note) for players covered by the July 2026
4for4 pull - not all 167 players have these yet. The draft simulator prefers
ADP over hand-curated rank when both exist (see `_expected_pick` in
analysis.py); the main Draft Board still groups by hand-curated tier.

Next up: weekly matchup/opponent analysis (start/sit, transaction-cap
tracking per the original Spec.MD Phase 3) - needs its own spec before
implementation. Also worth revisiting: surfacing ADP/delta-flag info in the
Draft Board UI itself (deferred as "data only" during the ADP import), and
Josh Jacobs's legal-risk note currently isn't a real flag category (stored
as a "note" field only, doesn't show on the Roster Risk Flags card) - would
need a frontend flag-map update in draftboard.js to fix properly.
