# EndZone Intel — Project Spec (Local, Personal Use)

## Goal
A local-only web app that pulls real data from your ESPN Fantasy league (roster, matchups, standings, free agents, transactions) and combines it with the tiered rankings / playbook rules / draft recommendation logic already built, so you get one tool instead of switching between ESPN's site and a static cheat sheet.

No hosting, no public deployment — runs on `localhost` on your own machine, started manually whenever you want it.

---

## 1. Data Access: ESPN Fantasy

ESPN has no official public API, but the **`espn-api`** Python package (actively maintained, MIT license) wraps their private endpoints and is the standard tool for this.

**What you'll need:**
- `league_id` — found in your league's ESPN URL (e.g. `.../leagueId=123456...`)
- `year` — season year (2026)
- For a **private league** (most are), two browser cookies:
  - `espn_s2`
  - `SWID`

**How to get the cookies:**
1. Log into ESPN Fantasy in your browser
2. Open DevTools → Application/Storage tab → Cookies → `fantasy.espn.com`
3. Copy the `espn_s2` and `SWID` values

**Treat these like a password** — they grant read access to your ESPN account's fantasy data. Store them in a local `.env` file, never commit them to any repo, never share them.

```python
from espn_api.football import League
league = League(league_id=123456, year=2026, espn_s2="...", swid="...")
```

From there the library exposes: teams, rosters, box scores, standings, free agents, transactions, and matchup schedules.

---

## 2. Recommended Stack (kept deliberately simple)

- **Backend:** Python + FastAPI (or Flask if you want even less ceremony) — thin wrapper around `espn-api`
- **Storage:** SQLite (a single local `.db` file — no server to manage) for caching pulled data between refreshes, so you're not hitting ESPN's endpoints constantly
- **Frontend:** Reuse the existing dark "war room" HTML/CSS/JS style from the draft board artifact, served as static files by the same backend
- **Refresh model:** A manual "Sync Now" button that re-pulls from ESPN on click, plus a simple `python refresh.py` script you can run anytime — no need for cloud scheduling since it's local

This avoids Docker, real databases, and deployment entirely — it's `pip install`, run one command, open `localhost:8000`.

---

## 3. Feature Scope (phased)

**Phase 1 — Read-only league mirror**
- Pull and display: your current roster, this week's matchup, league standings, recent transactions
- Cache to SQLite so the app works even if ESPN is slow/down temporarily

**Phase 2 — Merge with the existing tools**
- Import the tier board / target-watch stars / injury-scheme-committee flags as a local dataset (can literally start from the `PLAYERS` array already built)
- Cross-reference: flag any of *your* rostered players who carry a risk flag (injury/committee/scheme)
- Surface free agents currently on ESPN waivers who match your target/watch list

**Phase 3 — Weekly decision support**
- Start/sit suggestions: pull your bench vs. starters, cross-reference recent performance trend (the "declining trend vs. one bad week" rule) using ESPN's box-score history
- Transaction-cap tracker: count your moves this season live against the "cap your transactions" rule, with a visible counter/warning as you approach it
- Draft-day mode: keep the existing live draft board + recommendation engine, but pre-load your actual league size/settings pulled from ESPN instead of hardcoded 12-team assumptions

**Phase 4 (optional, only if you want it later)**
- Auto-refresh on a schedule using your OS's own task scheduler (Task Scheduler on Windows, `cron`/`launchd` on Mac) — still fully local, no cloud involved

---

## 4. Suggested Repo Structure

```
endzone-intel/
├── CLAUDE.md              # project context for Claude Code (see below)
├── .env                   # espn_s2, SWID, league_id — gitignored
├── .gitignore
├── requirements.txt
├── backend/
│   ├── main.py            # FastAPI app entrypoint
│   ├── espn_client.py      # espn-api wrapper functions
│   ├── db.py               # SQLite setup/queries
│   └── players.py          # tiered rankings + flags dataset (ported from draft board)
├── frontend/
│   ├── index.html
│   ├── styles.css          # reuse the turf/chalk/amber theme
│   └── app.js
└── refresh.py              # standalone "pull latest from ESPN" script
```

---

## 5. CLAUDE.md Starter (drop this in the repo root)

```markdown
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

## Current phase
Phase 1: read-only ESPN data mirror (roster, matchups, standings, transactions)
```

---

## 6. First Prompt to Give Claude Code

> "Set up a new local Python project called EndZone Intel per the attached spec. Start with Phase 1 only: a FastAPI backend that connects to ESPN Fantasy via the espn-api package, caches league data (roster, standings, matchups, transactions) in SQLite, and serves a simple dark-themed frontend showing that data. Use a `.env` file for league_id/espn_s2/SWID. I'll provide my actual league ID and cookies once the scaffold is ready."

Hand it this spec file directly — it has enough detail for Claude Code to scaffold the whole thing without much back-and-forth.

---

## 7. Building for Multi-League/Multi-Platform Later (Yahoo, Sleeper, etc.)

You don't need to build this now, but it's worth structuring Phase 1 so it's not a rewrite later:

- Define a generic **`LeagueProvider`** interface (e.g. `get_roster()`, `get_standings()`, `get_matchups()`, `get_transactions()`, `get_free_agents()`) that `espn_client.py` implements.
- All downstream logic (tier board, flags, start/sit rules, transaction-cap tracking) should read from this normalized interface, never from ESPN-specific data shapes directly.
- Adding Yahoo later becomes a new `yahoo_client.py` implementing the same interface, not a rework of Phases 2/3.

**Yahoo specifics, when you get there:** Yahoo has an **official** public Fantasy Sports API (OAuth 2.0) — more stable long-term than ESPN's unofficial endpoints, at the cost of a slightly more involved one-time setup (register an app on Yahoo's developer portal, do a one-time browser authorization, store a refresh token locally). Libraries like `yahoo_fantasy_api` / `yfpy` handle most of this. Once authorized, a local personal app can silently refresh the token going forward — no repeated logins.

---

## Notes
- If ESPN changes its private endpoints, the `espn-api` library is the thing that would need updating (community-maintained, usually patched quickly)
- Building the `LeagueProvider` abstraction now costs almost nothing extra in Phase 1, and turns "add Yahoo" from a rewrite into an afternoon project later

