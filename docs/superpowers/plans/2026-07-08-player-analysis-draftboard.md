# Player Analysis & Draft Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the standalone draft-board artifact's player/playbook data and UI into EndZone Intel, and cross-reference it against live ESPN roster/free-agent data.

**Architecture:** Player and playbook data live as plain Python data in `backend/players.py`. A new `backend/analysis.py` holds pure functions (recommendation engine, draft-state cycling, roster/free-agent cross-referencing) with no ESPN or FastAPI dependencies, so they're easy to reason about in isolation. `backend/main.py` exposes them via new endpoints. Draft state reuses the existing generic `cache` table — no schema change. Frontend adds a page nav (Dashboard / Draft Board / Playbook) and two new small JS files ported from the artifact's existing logic.

**Tech Stack:** Python/FastAPI backend (existing), vanilla JS/HTML/CSS frontend (existing), SQLite cache (existing).

## Global Constraints

- No automated test framework is introduced — this project has none by design (personal, single-user tool per `CLAUDE.md`). Verification is manual, via the running server (`curl` / browser), matching how Phase 1 was verified.
- Player matching between ESPN data and the ported dataset is by exact `name` string equality only — no fuzzy matching.
- Draft state uses the existing `db.set_cache` / `db.get_cache` key-value cache (key: `"draft_state"`) — do not create a new SQLite table.
- Source data for the port is `reference/draft-board.html` (checked into this repo) — the `PLAYERS` JS array (line ~578) and the nine `wr-pb-rule` playbook cards (line ~496 onward) in that file.
- Keep the existing dark turf/chalk/amber theme (`frontend/styles.css` `:root` variables) — new UI should feel consistent with the existing dashboard, not styled like a separate app.

---

### Task 1: Port player and playbook data

**Files:**
- Modify: `backend/players.py` (currently just `PLAYERS: list = []` placeholder)
- Source: `reference/draft-board.html` lines 578-725 (`PLAYERS` array), lines 496-569 (playbook rule cards)

**Interfaces:**
- Produces: `PLAYERS: list[dict]` — each dict has keys `rank` (int), `name` (str), `pos` (str), `team` (str), `tier` (int), `flags` (list[str], default `[]`), `target` (bool, default `False`), `watch` (bool, default `False`)
- Produces: `PLAYBOOK_RULES: list[dict]` — each dict has keys `title` (str), `body` (str), `evidence` (str)

- [ ] **Step 1: Transform the JS `PLAYERS` array into a Python list**

Read `reference/draft-board.html` lines 578-725. For each JS object literal like:
```js
{rank:3,name:"Christian McCaffrey",pos:"RB",team:"SF",tier:1,flags:["injury"],target:true},
```
write the equivalent Python dict, filling in the three optional keys explicitly when absent from the source:
```python
{"rank": 3, "name": "Christian McCaffrey", "pos": "RB", "team": "SF", "tier": 1,
 "flags": ["injury"], "target": True, "watch": False},
```
Do this for all 142 entries, preserving order. Assign the full list to `PLAYERS` in `backend/players.py`.

- [ ] **Step 2: Transform the nine playbook rule cards into `PLAYBOOK_RULES`**

For each `<div class="wr-pb-rule">` block in `reference/draft-board.html` (lines 496-569), extract the `<h3>` text as `title`, the `<p>` text (HTML stripped to plain text, keep `<b>`/`<i>` emphasis as plain text — no markup needed here) as `body`, and the `<div class="wr-pb-evidence">` text as `evidence`. Include the "Draft Shape: Round-by-Round Plan" card as the tenth entry (its body can keep the `<br>`-separated round guidance joined with newlines instead of `<br>`). Append all ten as dicts to `PLAYBOOK_RULES` in `backend/players.py`.

- [ ] **Step 3: Verify the data loads without errors**

Run: `cd backend && python -c "from players import PLAYERS, PLAYBOOK_RULES; print(len(PLAYERS), len(PLAYBOOK_RULES))"` from the repo's venv.
Expected: prints `142 10` (or the exact counts you ported — confirm both numbers are non-zero and match the source).

- [ ] **Step 4: Commit**

```bash
git add backend/players.py reference/draft-board.html
git commit -m "Port player tier data and playbook rules from draft board artifact"
```

---

### Task 2: Analysis engine — recommendation + draft-state cycling

**Files:**
- Create: `backend/analysis.py`

**Interfaces:**
- Consumes: `PLAYERS` list shape from Task 1 (`rank/name/pos/team/tier/flags/target/watch`)
- Produces: `compute_recommendation(players: list[dict], draft_state: dict) -> dict` returning `{"round": int, "counts": dict, "scored": list[dict]}` where each `scored` entry is `{"pos": str, "count": int, "min": int, "max": int, "label": str, "score": float, "need": int, "full": bool}`
- Produces: `cycle_draft_state(draft_state: dict, name: str) -> dict` — returns a **new** dict (does not mutate the input), cycling `name`'s state `absent -> "mine" -> "gone" -> absent`

- [ ] **Step 1: Write `compute_recommendation`**

This is a direct port of the artifact's `computeRecommendation()` (see `reference/draft-board.html` lines 741-770).

```python
"""Draft recommendation engine and roster/free-agent cross-referencing.

Pure functions only - no ESPN or FastAPI imports, so this stays testable
and reusable independent of how the data got here.
"""

LEAGUE_SIZE = 12
POSITION_TARGETS = {
    "RB": {"min": 5, "max": 6, "earliest": 1, "label": "RB"},
    "WR": {"min": 5, "max": 6, "earliest": 1, "label": "WR"},
    "QB": {"min": 2, "max": 2, "earliest": 7, "label": "QB"},
    "TE": {"min": 2, "max": 2, "earliest": 9, "label": "TE"},
    "DST": {"min": 1, "max": 1, "earliest": 14, "label": "D/ST"},
    "K": {"min": 1, "max": 1, "earliest": 15, "label": "K"},
}


def compute_recommendation(players: list, draft_state: dict) -> dict:
    my_players = [p for p in players if draft_state.get(p["name"]) == "mine"]
    total_picks = sum(1 for v in draft_state.values() if v in ("mine", "gone"))
    round_ = min(16, total_picks // LEAGUE_SIZE + 1)

    counts = {"RB": 0, "WR": 0, "QB": 0, "TE": 0, "DST": 0, "K": 0}
    for p in my_players:
        if p["pos"] in counts:
            counts[p["pos"]] += 1

    scored = []
    for pos, t in POSITION_TARGETS.items():
        count = counts[pos]
        need = max(0, t["min"] - count)
        if round_ < t["earliest"]:
            gap = t["earliest"] - round_
            weight = max(0.05, 1 - gap * 0.18) if need > 0 else 0
        else:
            overdue = round_ - t["earliest"]
            weight = 1 + overdue * 0.15
        bias = 0.05 if pos == "RB" else 0
        scored.append({
            "pos": pos, "count": count, "min": t["min"], "max": t["max"],
            "label": t["label"], "score": need * weight + bias,
            "need": need, "full": count >= t["max"],
        })

    scored.sort(key=lambda s: s["score"], reverse=True)
    return {"round": round_, "counts": counts, "scored": scored}
```

- [ ] **Step 2: Write `cycle_draft_state`**

```python
def cycle_draft_state(draft_state: dict, name: str) -> dict:
    current = draft_state.get(name)
    next_state = {None: "mine", "mine": "gone", "gone": None}[current]
    updated = dict(draft_state)
    if next_state is None:
        updated.pop(name, None)
    else:
        updated[name] = next_state
    return updated
```

- [ ] **Step 3: Verify manually**

Run from `backend/`:
```bash
python -c "
from analysis import compute_recommendation, cycle_draft_state
from players import PLAYERS

state = {}
state = cycle_draft_state(state, 'Jahmyr Gibbs')
print(state)  # expect {'Jahmyr Gibbs': 'mine'}
state = cycle_draft_state(state, 'Jahmyr Gibbs')
print(state)  # expect {'Jahmyr Gibbs': 'gone'}
state = cycle_draft_state(state, 'Jahmyr Gibbs')
print(state)  # expect {}

rec = compute_recommendation(PLAYERS, {'Jahmyr Gibbs': 'mine'})
print(rec['round'], rec['counts']['RB'], rec['scored'][0])
"
```
Expected: state dict transitions print as noted; round is `1`; RB count is `1`; the top-scored entry is whichever position still needs players most (RB or WR, given only one RB drafted so far).

- [ ] **Step 4: Commit**

```bash
git add backend/analysis.py
git commit -m "Add draft recommendation engine and draft-state cycling"
```

---

### Task 3: Analysis engine — roster and free-agent cross-referencing

**Files:**
- Modify: `backend/analysis.py`

**Interfaces:**
- Consumes: cached `roster` payload shape from `backend/espn_client.py`'s `_serialize_team`/`_serialize_player` (`{"team_id", "team_name", ..., "players": [{"name", "position", "pro_team", "injury_status", "lineup_slot", "total_points", "projected_total_points"}, ...]}`)
- Consumes: cached `free_agents` payload shape — a list of the same serialized player dicts (no team wrapper)
- Produces: `roster_risk_flags(roster: dict, players: list) -> list[dict]` — each result `{"name": str, "pos": str, "flags": list[str]}`
- Produces: `free_agent_matches(free_agents: list, players: list) -> list[dict]` — each result `{"name": str, "pos": str, "team": str, "tier": int, "target": bool, "watch": bool}`

- [ ] **Step 1: Write `roster_risk_flags`**

Append to `backend/analysis.py`:
```python
def roster_risk_flags(roster: dict, players: list) -> list:
    by_name = {p["name"]: p for p in players}
    flagged = []
    for rostered in roster.get("players", []):
        match = by_name.get(rostered["name"])
        if match and match["flags"]:
            flagged.append({"name": match["name"], "pos": match["pos"], "flags": match["flags"]})
    return flagged
```

- [ ] **Step 2: Write `free_agent_matches`**

```python
def free_agent_matches(free_agents: list, players: list) -> list:
    by_name = {p["name"]: p for p in players if p["target"] or p["watch"]}
    matches = []
    for fa in free_agents:
        match = by_name.get(fa["name"])
        if match:
            matches.append({
                "name": match["name"], "pos": match["pos"], "team": match["team"],
                "tier": match["tier"], "target": match["target"], "watch": match["watch"],
            })
    return matches
```

- [ ] **Step 3: Verify manually**

```bash
python -c "
from analysis import roster_risk_flags, free_agent_matches
from players import PLAYERS

roster = {'players': [{'name': 'Christian McCaffrey', 'position': 'RB'}, {'name': 'Nobody FA', 'position': 'RB'}]}
print(roster_risk_flags(roster, PLAYERS))  # expect one entry: McCaffrey, flags ['injury']

free_agents = [{'name': 'Rashee Rice', 'position': 'WR'}, {'name': 'Nobody FA', 'position': 'RB'}]
print(free_agent_matches(free_agents, PLAYERS))  # expect one entry: Rashee Rice (target: true)
"
```
Expected: first print shows exactly one dict for Christian McCaffrey with `flags: ['injury']`; second shows exactly one dict for Rashee Rice.

- [ ] **Step 4: Commit**

```bash
git add backend/analysis.py
git commit -m "Add roster risk-flag and free-agent target cross-referencing"
```

---

### Task 4: Wire free agents into sync

**Files:**
- Modify: `backend/sync.py`

**Interfaces:**
- Consumes: `LeagueProvider.get_free_agents(size: int = 50, position: Optional[str] = None) -> list` (already exists on `ESPNProvider`, `backend/espn_client.py:118-119`)
- Produces: a `"free_agents"` key in the `cache` table, populated on every `/api/sync` call, readable via `db.get_cache("free_agents")`

- [ ] **Step 1: Add the job**

In `backend/sync.py`, modify the `jobs` tuple in `run_sync`:
```python
    jobs = (
        ("roster", lambda: provider.get_roster(team_id)),
        ("standings", lambda: provider.get_standings()),
        ("matchups", lambda: provider.get_matchups()),
        ("transactions", lambda: provider.get_transactions()),
        ("free_agents", lambda: provider.get_free_agents()),
    )
```

- [ ] **Step 2: Verify via the running server**

With the server running (`uvicorn backend.main:app --port 8000` from repo root, venv active):
```bash
curl -s -X POST http://127.0.0.1:8000/api/sync
```
Expected: JSON response includes `"free_agents":"ok"` in `synced` (or a specific error string in `errors` if ESPN returns nothing pre-draft — either is fine, just confirm it's attempted and doesn't crash the whole endpoint).

- [ ] **Step 3: Commit**

```bash
git add backend/sync.py
git commit -m "Cache free agents on sync"
```

---

### Task 5: New API endpoints

**Files:**
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `players.PLAYERS`, `players.PLAYBOOK_RULES` (Task 1); `analysis.compute_recommendation`, `analysis.cycle_draft_state`, `analysis.roster_risk_flags`, `analysis.free_agent_matches` (Tasks 2-3); `db.get_cache`, `db.set_cache` (existing)
- Produces: `GET /api/players`, `POST /api/players/draft-state`, `POST /api/players/reset-draft-state`, `GET /api/playbook`, `GET /api/analysis/roster-flags`, `GET /api/analysis/free-agent-matches`

- [ ] **Step 1: Add imports and a shared helper**

In `backend/main.py`, add to the imports at the top:
```python
from pydantic import BaseModel

from . import analysis
from . import players as players_data
```

Add this helper near the other route handlers (it's called by three of the new routes below):
```python
def _players_payload():
    draft_state = (db.get_cache("draft_state") or {"data": {}})["data"]
    merged = [{**p, "state": draft_state.get(p["name"], "available")} for p in players_data.PLAYERS]
    recommendation = analysis.compute_recommendation(players_data.PLAYERS, draft_state)
    return {"players": merged, "recommendation": recommendation}
```

- [ ] **Step 2: Add the players and draft-state routes**

```python
@app.get("/api/players")
def players():
    return _players_payload()


class DraftStateRequest(BaseModel):
    name: str


@app.post("/api/players/draft-state")
def set_draft_state(body: DraftStateRequest):
    current = (db.get_cache("draft_state") or {"data": {}})["data"]
    updated = analysis.cycle_draft_state(current, body.name)
    db.set_cache("draft_state", updated)
    return _players_payload()


@app.post("/api/players/reset-draft-state")
def reset_draft_state():
    db.set_cache("draft_state", {})
    return _players_payload()
```

- [ ] **Step 3: Add the playbook and analysis routes**

```python
@app.get("/api/playbook")
def playbook():
    return {"rules": players_data.PLAYBOOK_RULES}


@app.get("/api/analysis/roster-flags")
def roster_flags():
    cached = db.get_cache("roster")
    if cached is None:
        return {"data": []}
    return {"data": analysis.roster_risk_flags(cached["data"], players_data.PLAYERS)}


@app.get("/api/analysis/free-agent-matches")
def free_agent_matches_endpoint():
    cached = db.get_cache("free_agents")
    if cached is None:
        return {"data": []}
    return {"data": analysis.free_agent_matches(cached["data"], players_data.PLAYERS)}
```

- [ ] **Step 4: Restart the server and verify each endpoint**

```bash
curl -s http://127.0.0.1:8000/api/players | head -c 300
curl -s -X POST http://127.0.0.1:8000/api/players/draft-state -H "Content-Type: application/json" -d '{"name":"Jahmyr Gibbs"}' | head -c 300
curl -s -X POST http://127.0.0.1:8000/api/players/reset-draft-state | head -c 200
curl -s http://127.0.0.1:8000/api/playbook | head -c 300
curl -s http://127.0.0.1:8000/api/analysis/roster-flags
curl -s http://127.0.0.1:8000/api/analysis/free-agent-matches
```
Expected: `/api/players` returns `{"players":[...142 entries...],"recommendation":{...}}`; the draft-state POST returns the same shape with Gibbs's `state` now `"mine"`; reset returns all `"state":"available"`; `/api/playbook` returns 10 rules; the two analysis endpoints return `{"data":[...]}` (possibly empty pre-draft, but must not error).

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "Add players, draft-state, playbook, and analysis API endpoints"
```

---

### Task 6: Frontend — page nav and Draft Board

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Create: `frontend/draftboard.js`

**Interfaces:**
- Consumes: `GET /api/players`, `POST /api/players/draft-state`, `POST /api/players/reset-draft-state` (Task 5)
- Consumes existing helpers from `frontend/app.js`: `apiGet(path)`, `setBody(id, html)`, `emptyState(message)` (these are plain global functions in a non-module script, so `draftboard.js` can call them directly as long as it's loaded after `app.js`)

- [ ] **Step 1: Add page nav and page wrappers to `index.html`**

Replace the `<main class="grid">...</main>` block in `frontend/index.html` with:
```html
  <nav class="page-nav">
    <button class="page-tab active" data-page="dashboard">Dashboard</button>
    <button class="page-tab" data-page="draftboard">Draft Board</button>
    <button class="page-tab" data-page="playbook">Playbook</button>
  </nav>

  <main class="page" id="page-dashboard">
  <div class="grid">
    <section class="card" id="roster-card">
      <h2>My Roster</h2>
      <div class="card-body" id="roster-body">Loading…</div>
    </section>

    <section class="card" id="matchups-card">
      <h2>This Week's Matchups</h2>
      <div class="card-body" id="matchups-body">Loading…</div>
    </section>

    <section class="card" id="standings-card">
      <h2>Standings</h2>
      <div class="card-body" id="standings-body">Loading…</div>
    </section>

    <section class="card" id="transactions-card">
      <h2>Recent Transactions</h2>
      <div class="card-body" id="transactions-body">Loading…</div>
    </section>

    <section class="card" id="roster-flags-card">
      <h2>Roster Risk Flags</h2>
      <div class="card-body" id="roster-flags-body">Loading…</div>
    </section>

    <section class="card" id="free-agent-matches-card">
      <h2>Free Agent Target Matches</h2>
      <div class="card-body" id="free-agent-matches-body">Loading…</div>
    </section>
  </div>
  </main>

  <main class="page hidden" id="page-draftboard">
    <div class="db-reco" id="db-reco">
      <div class="db-reco-top">
        <span class="db-reco-title">Draft Assistant</span>
        <span id="db-reco-round">Round 1</span>
      </div>
      <div class="db-reco-pick" id="db-reco-pick">Recommended: Best available RB or WR</div>
      <div class="db-reco-bars" id="db-reco-bars"></div>
    </div>

    <div class="db-controls">
      <input class="db-search" id="db-search" placeholder="Search a player..." />
      <button class="db-tab active" data-pos="ALL">All</button>
      <button class="db-tab" data-pos="QB">QB</button>
      <button class="db-tab" data-pos="RB">RB</button>
      <button class="db-tab" data-pos="WR">WR</button>
      <button class="db-tab" data-pos="TE">TE</button>
      <button class="db-tab" data-pos="DST">D/ST</button>
      <button class="db-tab" data-pos="K">K</button>
      <button class="db-toggle" id="db-toggle-targets">&#9733; My Targets</button>
      <button class="db-toggle" id="db-toggle-watch">&#9734; Watch List</button>
      <button class="db-toggle" id="db-hide-drafted">Hide drafted</button>
    </div>

    <div class="db-list" id="db-list"></div>

    <div class="db-footer">
      <span id="db-count">Loading board...</span>
      <button class="db-reset" id="db-reset">Reset drafted picks</button>
    </div>
  </main>

  <main class="page hidden" id="page-playbook">
    <div class="pb-intro">Rules built from what actually happened to Team Nepotism in 2025 — not generic advice.</div>
    <div id="pb-list">Loading…</div>
  </main>
```

- [ ] **Step 2: Add page-nav and draft-board CSS to `styles.css`**

Append to `frontend/styles.css`:
```css
.page-nav {
  display: flex;
  gap: 0.5rem;
  padding: 0 2rem;
  background: rgba(0, 0, 0, 0.25);
  border-bottom: 1px solid rgba(255, 183, 3, 0.15);
}

.page-tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--chalk-dim);
  padding: 0.9rem 0.25rem;
  margin-right: 1.25rem;
  font-size: 0.85rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  cursor: pointer;
}

.page-tab:hover { color: var(--chalk); }
.page-tab.active { color: var(--amber); border-bottom-color: var(--amber); }

.page.hidden { display: none; }

.db-reco {
  margin: 1.25rem 2rem 0;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 183, 3, 0.2);
  border-left: 3px solid #6ea86e;
  border-radius: 8px;
  padding: 0.9rem 1.1rem;
}

.db-reco-top {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: var(--chalk-dim);
  margin-bottom: 0.5rem;
}

.db-reco-pick { font-size: 1rem; font-weight: 700; color: #6ea86e; margin-bottom: 0.6rem; }

.db-reco-bars {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.5rem;
}

.db-reco-bar-label { display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--chalk-dim); margin-bottom: 0.2rem; }
.db-reco-bar-track { background: rgba(0,0,0,0.4); border-radius: 3px; height: 6px; overflow: hidden; }
.db-reco-bar-fill { height: 100%; background: var(--chalk-dim); border-radius: 3px; }
.db-reco-bar-fill.met { background: #6ea86e; }
.db-reco-bar-fill.recommended { background: var(--amber); }

.db-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 1rem 2rem;
}

.db-search {
  flex: 1;
  min-width: 160px;
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(255,183,3,0.2);
  color: var(--chalk);
  padding: 0.55rem 0.75rem;
  border-radius: 6px;
  font-family: inherit;
}

.db-tab, .db-toggle {
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(255,183,3,0.2);
  color: var(--chalk-dim);
  padding: 0.55rem 0.85rem;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  border-radius: 6px;
  cursor: pointer;
}

.db-tab.active, .db-toggle.active { background: var(--amber); color: #1a1300; border-color: var(--amber); }

.db-list { padding: 0.5rem 2rem 2rem; }

.db-tier-head {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--amber);
  font-weight: 700;
  margin: 1.25rem 0 0.5rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid rgba(255,183,3,0.15);
}

.db-row {
  display: grid;
  grid-template-columns: 34px 1fr auto auto;
  align-items: center;
  gap: 0.6rem;
  padding: 0.5rem;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
}

.db-row:hover { background: rgba(0,0,0,0.25); border-color: rgba(255,183,3,0.15); }
.db-row.mine { background: rgba(110,168,110,0.12); border-color: #6ea86e; }
.db-row.mine .db-name { color: #6ea86e; }
.db-row.gone { opacity: 0.35; }
.db-row.gone .db-name { text-decoration: line-through; }

.db-rank { font-family: Consolas, monospace; color: var(--chalk-dim); font-size: 0.8rem; text-align: right; }
.db-name { font-weight: 700; }
.db-meta { font-size: 0.7rem; color: var(--chalk-dim); }

.db-pos-badge {
  font-size: 0.65rem;
  font-weight: 800;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  background: rgba(255,183,3,0.15);
  color: var(--amber);
}

.db-star { color: var(--amber); margin-right: 0.2rem; }
.db-watch-star { color: #5b8bb0; margin-right: 0.2rem; }

.db-draft-btn {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  padding: 0.35rem 0.6rem;
  border-radius: 4px;
  border: 1px solid rgba(255,183,3,0.2);
  background: transparent;
  color: var(--chalk-dim);
  white-space: nowrap;
}

.db-row.gone .db-draft-btn { background: var(--amber-dim); color: var(--chalk); }
.db-row.mine .db-draft-btn { background: #6ea86e; color: #07281896; }

.db-footer {
  position: sticky;
  bottom: 0;
  background: rgba(0,0,0,0.5);
  border-top: 1px solid rgba(255,183,3,0.15);
  padding: 0.7rem 2rem;
  font-size: 0.8rem;
  color: var(--chalk-dim);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.db-reset {
  background: transparent;
  border: 1px solid var(--danger);
  color: var(--danger);
  padding: 0.4rem 0.8rem;
  border-radius: 6px;
  font-size: 0.7rem;
  font-weight: 700;
  cursor: pointer;
}

.pb-intro { color: var(--chalk-dim); padding: 1rem 2rem 0; font-size: 0.9rem; }

.pb-rule {
  margin: 1rem 2rem;
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(255,183,3,0.2);
  border-left: 3px solid var(--amber);
  border-radius: 8px;
  padding: 1rem 1.2rem;
}

.pb-rule h3 { margin: 0 0 0.4rem; font-size: 0.9rem; text-transform: uppercase; }
.pb-rule p { margin: 0; font-size: 0.85rem; color: var(--chalk-dim); line-height: 1.5; white-space: pre-line; }
.pb-evidence { margin-top: 0.5rem; font-size: 0.75rem; color: #8a8f86; font-style: italic; }
```

- [ ] **Step 3: Create `frontend/draftboard.js`**

```javascript
const FLAG_CLASS = { injury: '#b5533f', committee: '#8a8f86', breakout: '#6ea86e', rookie: '#5b8bb0', scheme: '#8a6bb0' };
const FLAG_LABEL = { injury: 'Injury history', committee: 'Committee risk', breakout: 'Breakout watch', rookie: 'Rookie / unproven', scheme: 'Scheme / role change risk' };

let dbPlayers = [];
let dbRecommendation = null;
let dbActivePos = 'ALL';
let dbHideDrafted = false;
let dbTargetsOnly = false;
let dbWatchOnly = false;
let dbSearchTerm = '';
let dbLoaded = false;

function renderDbRecommendation() {
  if (!dbRecommendation) return;
  document.getElementById('db-reco-round').textContent = `Round ${dbRecommendation.round}`;
  const top = dbRecommendation.scored.filter((s) => s.score > 0.01).slice(0, 2);
  const pickEl = document.getElementById('db-reco-pick');
  if (top.length === 0) {
    pickEl.textContent = 'Position needs met — take the best player available.';
  } else if (top.length === 1 || top[1].score < top[0].score * 0.5) {
    pickEl.textContent = `Recommended: ${top[0].label}`;
  } else {
    pickEl.textContent = `Recommended: ${top[0].label} or ${top[1].label}`;
  }
  const topPos = top.length ? top[0].pos : null;
  document.getElementById('db-reco-bars').innerHTML = dbRecommendation.scored
    .map((s) => {
      const pct = Math.min(100, Math.round((s.count / s.max) * 100));
      const fillClass = s.full ? 'met' : (s.pos === topPos ? 'recommended' : '');
      return `
        <div>
          <div class="db-reco-bar-label"><span>${s.label}</span><span>${s.count}/${s.min}${s.max > s.min ? '-' + s.max : ''}</span></div>
          <div class="db-reco-bar-track"><div class="db-reco-bar-fill ${fillClass}" style="width:${pct}%"></div></div>
        </div>`;
    })
    .join('');
}

function renderDbList() {
  const term = dbSearchTerm.trim().toLowerCase();
  let filtered = dbPlayers.filter((p) => {
    if (dbActivePos !== 'ALL' && p.pos !== dbActivePos) return false;
    if (term && !p.name.toLowerCase().includes(term)) return false;
    if (dbHideDrafted && p.state !== 'available') return false;
    if (dbTargetsOnly && !p.target) return false;
    if (dbWatchOnly && !p.watch) return false;
    return true;
  });
  filtered.sort((a, b) => a.tier - b.tier || a.rank - b.rank);

  const listEl = document.getElementById('db-list');
  if (filtered.length === 0) {
    listEl.innerHTML = emptyState('No players match. Try a different search or filter.');
  } else {
    let html = '';
    let lastTier = null;
    filtered.forEach((p) => {
      if (p.tier !== lastTier) {
        html += `<div class="db-tier-head">Tier ${p.tier}</div>`;
        lastTier = p.tier;
      }
      const rowClass = p.state === 'mine' ? 'mine' : (p.state === 'gone' ? 'gone' : '');
      const flags = (p.flags || [])
        .map((f) => `<span title="${FLAG_LABEL[f]}" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${FLAG_CLASS[f]}"></span>`)
        .join(' ');
      const star = p.target ? '<span class="db-star" title="Top target">&#9733;</span>' : (p.watch ? '<span class="db-watch-star" title="Watch">&#9734;</span>' : '');
      let btnLabel = 'Mark';
      if (p.state === 'mine') btnLabel = 'On My Team';
      if (p.state === 'gone') btnLabel = 'Off Board';
      html += `
        <div class="db-row ${rowClass}" data-name="${encodeURIComponent(p.name)}">
          <div class="db-rank">${p.rank}</div>
          <div>
            <div class="db-name">${star}${p.name}</div>
            <div class="db-meta">${p.team}</div>
          </div>
          <div><span class="db-pos-badge">${p.pos === 'DST' ? 'D/ST' : p.pos}</span> ${flags}</div>
          <button class="db-draft-btn">${btnLabel}</button>
        </div>`;
    });
    listEl.innerHTML = html;
  }

  const mineCount = dbPlayers.filter((p) => p.state === 'mine').length;
  const goneCount = dbPlayers.filter((p) => p.state === 'gone').length;
  document.getElementById('db-count').textContent = `${filtered.length} shown · ${mineCount} on my team · ${goneCount} off board`;

  listEl.querySelectorAll('.db-row').forEach((row) => {
    row.onclick = async () => {
      const name = decodeURIComponent(row.getAttribute('data-name'));
      await markDraftState(name);
    };
  });
}

async function markDraftState(name) {
  const res = await fetch('/api/players/draft-state', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const body = await res.json();
  dbPlayers = body.players;
  dbRecommendation = body.recommendation;
  renderDbRecommendation();
  renderDbList();
}

async function loadDraftBoard() {
  if (dbLoaded) return;
  dbLoaded = true;
  try {
    const body = await apiGet('/api/players');
    dbPlayers = body.players;
    dbRecommendation = body.recommendation;
    renderDbRecommendation();
    renderDbList();
  } catch (err) {
    document.getElementById('db-list').innerHTML = emptyState(err.message);
  }
}

document.getElementById('db-search').addEventListener('input', (e) => { dbSearchTerm = e.target.value; renderDbList(); });
document.querySelectorAll('.db-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.db-tab').forEach((t) => t.classList.remove('active'));
    tab.classList.add('active');
    dbActivePos = tab.getAttribute('data-pos');
    renderDbList();
  });
});
document.getElementById('db-toggle-targets').addEventListener('click', (e) => { dbTargetsOnly = !dbTargetsOnly; e.target.classList.toggle('active', dbTargetsOnly); renderDbList(); });
document.getElementById('db-toggle-watch').addEventListener('click', (e) => { dbWatchOnly = !dbWatchOnly; e.target.classList.toggle('active', dbWatchOnly); renderDbList(); });
document.getElementById('db-hide-drafted').addEventListener('click', (e) => { dbHideDrafted = !dbHideDrafted; e.target.textContent = dbHideDrafted ? 'Show drafted' : 'Hide drafted'; renderDbList(); });
document.getElementById('db-reset').addEventListener('click', async () => {
  if (!confirm('Clear all drafted marks?')) return;
  const res = await fetch('/api/players/reset-draft-state', { method: 'POST' });
  const body = await res.json();
  dbPlayers = body.players;
  dbRecommendation = body.recommendation;
  renderDbRecommendation();
  renderDbList();
});
```

- [ ] **Step 4: Wire up page nav switching and load-on-first-view in `frontend/app.js`**

Append to the bottom of `frontend/app.js` (before the final `loadAll();` line, or after — order doesn't matter since these are just event listener registrations):
```javascript
document.querySelectorAll('.page-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.page-tab').forEach((t) => t.classList.remove('active'));
    tab.classList.add('active');
    const page = tab.getAttribute('data-page');
    document.querySelectorAll('.page').forEach((el) => el.classList.add('hidden'));
    document.getElementById(`page-${page}`).classList.remove('hidden');
    if (page === 'draftboard') loadDraftBoard();
    if (page === 'playbook') loadPlaybook();
  });
});
```

- [ ] **Step 5: Add the script tag to `index.html`**

In `frontend/index.html`, after `<script src="/app.js"></script>`, add:
```html
  <script src="/draftboard.js"></script>
```

- [ ] **Step 6: Verify in a browser**

Start the server (`uvicorn backend.main:app --port 8000` from repo root, venv active), open `http://127.0.0.1:8000`, click the "Draft Board" tab. Confirm: 142 players render grouped by tier; search filters the list; position tabs filter; clicking a player cycles it through available → mine (green) → gone (struck through) → available; the recommendation panel updates round/position bars as you mark players "mine"; "Reset drafted picks" clears everything after confirming.

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html frontend/styles.css frontend/draftboard.js frontend/app.js
git commit -m "Add Draft Board page with search, filters, and live recommendation"
```

---

### Task 7: Frontend — Playbook page

**Files:**
- Create: `frontend/playbook.js`
- Modify: `frontend/index.html` (add script tag)

**Interfaces:**
- Consumes: `GET /api/playbook` (Task 5), `apiGet`/`emptyState` globals from `app.js`

- [ ] **Step 1: Create `frontend/playbook.js`**

```javascript
let pbLoaded = false;

async function loadPlaybook() {
  if (pbLoaded) return;
  pbLoaded = true;
  const listEl = document.getElementById('pb-list');
  try {
    const body = await apiGet('/api/playbook');
    listEl.innerHTML = body.rules
      .map(
        (r) => `
        <div class="pb-rule">
          <h3>${r.title}</h3>
          <p>${r.body}</p>
          <div class="pb-evidence">Evidence: ${r.evidence}</div>
        </div>`
      )
      .join('');
  } catch (err) {
    listEl.innerHTML = emptyState(err.message);
  }
}
```

- [ ] **Step 2: Add the script tag to `index.html`**

In `frontend/index.html`, after `<script src="/draftboard.js"></script>`, add:
```html
  <script src="/playbook.js"></script>
```

- [ ] **Step 3: Verify in a browser**

Reload the app, click the "Playbook" tab. Confirm all 10 rule cards render with title, body, and evidence line, styled consistently with the rest of the app.

- [ ] **Step 4: Commit**

```bash
git add frontend/playbook.js frontend/index.html
git commit -m "Add Playbook page"
```

---

### Task 8: Frontend — Dashboard analysis cards

**Files:**
- Modify: `frontend/app.js`

**Interfaces:**
- Consumes: `GET /api/analysis/roster-flags`, `GET /api/analysis/free-agent-matches` (Task 5)

- [ ] **Step 1: Add render functions**

Add to `frontend/app.js`, near the other `render*` functions:
```javascript
function renderRosterFlags(data) {
  if (data.length === 0) {
    setBody('roster-flags-body', emptyState('No risk-flagged players on your roster yet.'));
    return;
  }
  const rows = data
    .map((p) => `<tr><td>${p.name}</td><td>${p.pos}</td><td>${p.flags.join(', ')}</td></tr>`)
    .join('');
  setBody(
    'roster-flags-body',
    `<table><thead><tr><th>Player</th><th>Pos</th><th>Flags</th></tr></thead><tbody>${rows}</tbody></table>`
  );
}

function renderFreeAgentMatches(data) {
  if (data.length === 0) {
    setBody('free-agent-matches-body', emptyState('No target/watch-list players currently on waivers.'));
    return;
  }
  const rows = data
    .map((p) => `<tr><td>${p.name}</td><td>${p.pos}</td><td>${p.team}</td><td>${p.target ? 'Target' : 'Watch'}</td></tr>`)
    .join('');
  setBody(
    'free-agent-matches-body',
    `<table><thead><tr><th>Player</th><th>Pos</th><th>Team</th><th>List</th></tr></thead><tbody>${rows}</tbody></table>`
  );
}
```

- [ ] **Step 2: Add both to the `SECTIONS` array**

Modify the `SECTIONS` array in `frontend/app.js`:
```javascript
const SECTIONS = [
  { key: 'roster', path: '/api/roster', render: renderRoster },
  { key: 'matchups', path: '/api/matchups', render: renderMatchups },
  { key: 'standings', path: '/api/standings', render: renderStandings },
  { key: 'transactions', path: '/api/transactions', render: renderTransactions },
  { key: 'roster-flags', path: '/api/analysis/roster-flags', render: (body) => renderRosterFlags(body.data) },
  { key: 'free-agent-matches', path: '/api/analysis/free-agent-matches', render: (body) => renderFreeAgentMatches(body.data) },
];
```

**Note:** the existing `loadSection` calls `section.render(cached.data)` where `cached` is the full `apiGet` response — for the four existing sections, the backend already wraps payloads as `{"data": ..., "updated_at": ...}` via `_cached_or_404`, so `cached.data` is the inner payload. The two new analysis endpoints return `{"data": [...]}` directly with no `updated_at` (Task 5, Step 3) — same `.data` access pattern works unchanged, but the render functions above expect the raw list, so keep the inline-arrow wrapping shown (`(body) => renderRosterFlags(body.data)`) exactly as written — do not change `loadSection` itself, since `cached.data` already extracts the list correctly before calling `section.render`.

Also note these two new endpoints don't 404 when unsynced (Task 5 returns `{"data": []}`, not a 404) — so `loadSection`'s existing catch-block behavior (showing `emptyState(err.message)` on a thrown error) won't trigger for these two; the empty-state messaging comes from inside `renderRosterFlags`/`renderFreeAgentMatches` themselves when `data.length === 0`, which is why those functions check `data.length === 0` explicitly rather than relying on the fetch failing.

- [ ] **Step 3: Verify in a browser**

Reload the app's Dashboard tab. Confirm "Roster Risk Flags" and "Free Agent Target Matches" cards appear, showing their respective empty-state messages (expected pre-draft, since roster is empty and free agents haven't necessarily synced yet). Run "Sync Now" and confirm both cards still render without error (empty or populated, depending on current ESPN data).

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "Add roster risk-flag and free-agent match cards to dashboard"
```

---

## Final Verification

After all 8 tasks are committed:

1. Restart the server fresh: `uvicorn backend.main:app --port 8000` from the repo root (venv active).
2. Run `curl -s -X POST http://127.0.0.1:8000/api/sync` — confirm no 500s, all five sync jobs report `"ok"` or a specific non-crashing error.
3. Open `http://127.0.0.1:8000` in a browser. Walk all three pages (Dashboard, Draft Board, Playbook) and exercise every control (search, position tabs, target/watch toggles, hide-drafted, mark-as-drafted, reset, sync).
4. Confirm `git log --oneline -10` shows all 8 task commits plus the two design/spec commits from brainstorming, all on `claude/endzone-intel-phase-1-jaai5i`.
