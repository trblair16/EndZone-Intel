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
(`get_espn_rankings`) for players outside that pull. The draft simulator
prefers ADP, then the ESPN rank fallback, over hand-curated rank (see
`_expected_pick` in analysis.py); the main Draft Board still groups by
hand-curated tier but now also shows the ADP round + riser/faller badge
per player. Josh Jacobs's legal-risk note is now a real 'legal' flag
(shows on the Roster Risk Flags card), not just free text.

Next up: weekly matchup/opponent analysis for start/sit decisions and
transaction-cap tracking (Spec.MD Phase 3), plus trade analytics - both
need their own spec before implementation. Yahoo league support
(a `yahoo_client.py` implementing `LeagueProvider`, per Spec.MD section 7)
is unstarted; it also needs a one-time OAuth app registration on Yahoo's
developer portal, which only the user can do.

Known caveat: `get_espn_rankings`'s single size=300 request is an
untested assumption (see the comment in espn_client.py) - worth
confirming it doesn't truncate against a real league before relying on
it live.
