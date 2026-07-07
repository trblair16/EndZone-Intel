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
Phase 1: read-only ESPN data mirror (roster, matchups, standings, transactions)
