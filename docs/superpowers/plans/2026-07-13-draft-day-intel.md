# Draft-Day Intel Additions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add player news, an ESPN-sourced live ADP fallback, bye-week collision warnings, and weekly opponent info — all four sourced from ESPN data already reachable through the existing authenticated connection, no external scraping or new dependencies.

**Architecture:** Each feature adds one or two `ESPNProvider` methods, wires new sync jobs into the existing cache pipeline where the data is bulk/periodic, or exposes an on-demand endpoint where it isn't (player news). `players.py` is never mutated automatically — live ESPN data merges with the static dataset at read time, matching every prior feature in this app.

**Tech Stack:** Python/FastAPI backend (existing), vanilla JS/HTML/CSS frontend (existing), `espn-api` (already installed) — no new dependencies.

## Global Constraints

- `players.py` stays hand-curated; nothing in this plan writes to it automatically.
- No automated test framework (none exists in this project by design). Verification is manual via `curl`/Python one-liners and a browser, same as every prior phase.
- Every new endpoint/data path must degrade gracefully (empty result, not a crash) when ESPN returns nothing — matches the existing convention set by `get_matchups()`'s pre-draft `KeyError` handling.
- The bye-week table below was researched via web search on 2026-07-13 (cross-checked against two independent sources, consistent on the Week 11 breakdown) — spot-check it against ESPN or NFL.com before trusting it fully on draft day.
- `get_espn_rankings`'s bulk-request size is an untested assumption (only `size=5` was verified live during design) — Task 3 includes a live verification step specifically to catch this, with a pagination fallback path if a single large request fails or truncates.

---

### Task 1: Player news — backend

**Files:**
- Modify: `backend/espn_client.py`
- Modify: `backend/main.py`

**Interfaces:**
- Produces: `LeagueProvider.get_player_news(player_id: int, size: int = 5) -> list[dict]` (abstract + `ESPNProvider` implementation), each dict shaped `{"headline": str, "description": str, "published": str}`
- Produces: `GET /api/players/{player_id}/news` returning `{"news": [...]}`
- Modifies: `ESPNProvider._serialize_player()` to include `"player_id": player.playerId` so the frontend has an ID to call this endpoint with

- [ ] **Step 1: Add `player_id` to `_serialize_player`**

In `backend/espn_client.py`, modify `_serialize_player` (currently at lines 65-75):

```python
    @staticmethod
    def _serialize_player(player) -> dict:
        return {
            "player_id": player.playerId,
            "name": player.name,
            "position": player.position,
            "pro_team": player.proTeam,
            "injury_status": player.injuryStatus,
            "lineup_slot": player.lineupSlot,
            "total_points": player.total_points,
            "projected_total_points": player.projected_total_points,
        }
```

- [ ] **Step 2: Add the abstract method and implementation**

Add to `LeagueProvider` (after `get_live_picks`, currently lines 36-38):

```python
    @abstractmethod
    def get_player_news(self, player_id: int, size: int = 5) -> list:
        ...
```

Add to `ESPNProvider` (after `get_live_picks`, currently lines 133-141):

```python
    def get_player_news(self, player_id: int, size: int = 5) -> list:
        data = self._league.espn_request.get_player_news(playerId=player_id)
        feed = data.get("news", {}).get("feed", [])
        return [
            {
                "headline": item.get("headline"),
                "description": item.get("description"),
                "published": item.get("published"),
            }
            for item in feed[:size]
        ]
```

- [ ] **Step 3: Add the endpoint**

In `backend/main.py`, add after `free_agent_matches_endpoint` (currently ends line 135) and before `_simulator_state_payload`:

```python
@app.get("/api/players/{player_id}/news")
def player_news(player_id: int):
    try:
        provider = build_provider()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"news": provider.get_player_news(player_id)}
```

- [ ] **Step 4: Verify manually**

Restart the server (`uvicorn backend.main:app --port 8000` from repo root, venv active), then:
```bash
curl -s -X POST http://127.0.0.1:8000/api/sync
curl -s http://127.0.0.1:8000/api/roster | python3 -c "
import json, sys
d = json.load(sys.stdin)
players = d['data']['players']
if players:
    print(players[0]['name'], players[0]['player_id'])
else:
    print('roster empty - pre-draft, expected')
"
```
If your roster has players, grab one `player_id` from the output and:
```bash
curl -s http://127.0.0.1:8000/api/players/<player_id>/news | head -c 500
```
Expected: `{"news": [...]}` with headline/description/published fields, or `{"news": []}` if ESPN has nothing — either way, no 500.

- [ ] **Step 5: Commit**

```bash
git add backend/espn_client.py backend/main.py
git commit -m "Add player news endpoint sourced from ESPN's own news feed"
```

---

### Task 2: Player news — frontend

**Files:**
- Modify: `frontend/app.js`

**Interfaces:**
- Consumes: `GET /api/players/{player_id}/news` (Task 1)

- [ ] **Step 1: Add a news-loading helper and render function**

Add to `frontend/app.js`, after `renderFreeAgentMatches` (currently ends line 155):

```javascript
async function loadPlayerNews(playerId, containerId) {
  const el = document.getElementById(containerId);
  el.textContent = 'Loading news...';
  try {
    const body = await apiGet(`/api/players/${playerId}/news`);
    if (body.news.length === 0) {
      el.innerHTML = emptyState('No recent news.');
      return;
    }
    el.innerHTML = body.news
      .map(
        (n) => `
        <div class="news-item">
          <div class="news-headline">${n.headline}</div>
          <div class="news-date">${n.published ? new Date(n.published).toLocaleDateString() : ''}</div>
        </div>`
      )
      .join('');
  } catch (err) {
    el.innerHTML = emptyState(err.message);
  }
}
```

- [ ] **Step 2: Add a "News" toggle button per player row on the roster and free-agent-matches cards**

Modify `renderRoster` in `frontend/app.js` (currently lines 48-68) to add a news button/row per player:

```javascript
function renderRoster(data) {
  const players = data.players
    .map(
      (p) => `
      <tr>
        <td>${p.name}${p.injury_status && p.injury_status !== 'ACTIVE' ? ` <span class="tag tag-injury">${p.injury_status}</span>` : ''}
          <button class="news-btn" data-player-id="${p.player_id}" data-news-id="news-roster-${p.player_id}">News</button>
          <div class="news-panel hidden" id="news-roster-${p.player_id}"></div>
        </td>
        <td>${p.position}</td>
        <td>${p.pro_team}</td>
        <td>${p.total_points}</td>
      </tr>`
    )
    .join('');
  setBody(
    'roster-body',
    `<p>${data.team_name} (${data.wins}-${data.losses}${data.ties ? `-${data.ties}` : ''})</p>
     <table>
       <thead><tr><th>Player</th><th>Pos</th><th>Team</th><th>Pts</th></tr></thead>
       <tbody>${players}</tbody>
     </table>`
  );
  wireNewsButtons();
}
```

Modify `renderFreeAgentMatches` (currently lines 143-155) the same way — note free-agent-match records don't currently carry `player_id` (`analysis.free_agent_matches` doesn't include it). Skip adding a News button there for now; it needs `player_id` threaded through `analysis.free_agent_matches` first, which is out of scope for this plan (the free-agent cross-reference match dict is built in `backend/analysis.py`'s `free_agent_matches`, keyed only by name/pos/team/tier/target/watch — extending it isn't part of this plan's Task 1 changes). Only the roster card gets News buttons in this pass.

- [ ] **Step 3: Add the click-wiring helper**

Add to `frontend/app.js`, after `loadPlayerNews`:

```javascript
function wireNewsButtons() {
  document.querySelectorAll('.news-btn').forEach((btn) => {
    btn.onclick = () => {
      const playerId = btn.getAttribute('data-player-id');
      const newsId = btn.getAttribute('data-news-id');
      const panel = document.getElementById(newsId);
      const wasHidden = panel.classList.contains('hidden');
      if (wasHidden) {
        panel.classList.remove('hidden');
        loadPlayerNews(playerId, newsId);
      } else {
        panel.classList.add('hidden');
      }
    };
  });
}
```

- [ ] **Step 4: Add CSS for the news button/panel**

Append to `frontend/styles.css`:

```css
.news-btn {
  font-size: 0.65rem;
  padding: 0.15rem 0.4rem;
  margin-left: 0.4rem;
  background: transparent;
  border: 1px solid rgba(255,183,3,0.3);
  color: var(--amber);
  border-radius: 4px;
  cursor: pointer;
}

.news-panel {
  margin-top: 0.4rem;
  font-size: 0.8rem;
  color: var(--chalk-dim);
}

.news-panel.hidden { display: none; }

.news-item { margin-bottom: 0.5rem; }
.news-headline { color: var(--chalk); }
.news-date { font-size: 0.7rem; color: #8a8f86; }
```

- [ ] **Step 5: Syntax-check and verify in a browser**

```bash
cd "$HOME/source/repos/EndZone-Intel/frontend" && node --check app.js
```
Then in the browser: sync, open the Dashboard, click "News" next to a rostered player, confirm it expands with headlines (or "No recent news."), click again to collapse.

- [ ] **Step 6: Commit**

```bash
git add frontend/app.js frontend/styles.css
git commit -m "Add on-demand player news panel to the roster card"
```

---

### Task 3: ESPN's own draft-rank data — backend

**Files:**
- Modify: `backend/espn_client.py`
- Modify: `backend/sync.py`

**Interfaces:**
- Produces: `LeagueProvider.get_espn_rankings(size: int = 300) -> dict` (abstract + `ESPNProvider`), returning `{player_name: ppr_rank_int}`
- Adds `"espn_rankings"` as a sync job

- [ ] **Step 1: Add the abstract method and implementation**

Add to `LeagueProvider` (after `get_player_news`):

```python
    @abstractmethod
    def get_espn_rankings(self, size: int = 300) -> dict:
        ...
```

Add to `ESPNProvider` (after `get_player_news`). Requires `import json` at the top of the file:

```python
    def get_espn_rankings(self, size: int = 300) -> dict:
        params = {"view": "kona_player_info"}
        headers = {
            "x-fantasy-filter": json.dumps({
                "players": {
                    "limit": size,
                    "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "PPR"},
                    "filterRanksForRankTypes": {"value": ["PPR"]},
                }
            })
        }
        data = self._league.espn_request.league_get(params=params, headers=headers)
        rankings = {}
        for entry in data.get("players", []):
            player = entry.get("player", {})
            name = player.get("fullName")
            ppr = player.get("draftRanksByRankType", {}).get("PPR", {})
            if name and "rank" in ppr:
                rankings[name] = ppr["rank"]
        return rankings
```

Add `import json` near the top of `backend/espn_client.py`, alongside the existing `from abc import ABC, abstractmethod` / `from typing import Optional` imports.

- [ ] **Step 2: Verify the size=300 assumption live BEFORE wiring into sync**

This is the step that tests the Global Constraints caveat about untested bulk size:

```bash
cd "$HOME/source/repos/EndZone-Intel" && source .venv/Scripts/activate
python3 -c "
from backend.espn_client import build_provider
provider = build_provider()
rankings = provider.get_espn_rankings(size=300)
print('total players returned:', len(rankings))
print('sample:', list(rankings.items())[:5])
"
```
Expected: a few hundred entries (roughly 250-300), no exception. **If this errors, returns far fewer than 300 entries, or the response looks truncated/malformed:** switch to pagination using the existing `offset` field in the filter (same pattern as `get_free_agents`), fetching in batches of e.g. 50 with `offset` incrementing, merging the results, and adjust the implementation accordingly before proceeding to Step 3.

- [ ] **Step 3: Wire into sync**

In `backend/sync.py`, modify the `jobs` tuple (currently lines 12-18):

```python
    jobs = (
        ("roster", lambda: provider.get_roster(team_id)),
        ("standings", lambda: provider.get_standings()),
        ("matchups", lambda: provider.get_matchups()),
        ("transactions", lambda: provider.get_transactions()),
        ("free_agents", lambda: provider.get_free_agents()),
        ("espn_rankings", lambda: provider.get_espn_rankings()),
    )
```

- [ ] **Step 4: Verify via the running server**

```bash
uvicorn backend.main:app --port 8000
```
In another terminal:
```bash
curl -s -X POST http://127.0.0.1:8000/api/sync
```
Expected: `"espn_rankings":"ok"` in the `synced` object, no error.

- [ ] **Step 5: Commit**

```bash
git add backend/espn_client.py backend/sync.py
git commit -m "Add ESPN's own PPR draft-rank sync as a live ADP fallback source"
```

---

### Task 4: Wire ESPN rankings into the recommendation/simulator engine

**Files:**
- Modify: `backend/analysis.py`
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: cached `"espn_rankings"` dict (Task 3)
- Modifies: `_expected_pick(player: dict, espn_rankings: dict = None) -> int` and `simulate_board_at_pick(players: list, sim_state: dict, overall_pick: int, espn_rankings: dict = None) -> dict` to accept an optional rankings dict, checked between `_EXPECTED_PICK_OVERRIDES` and the raw `rank` fallback

- [ ] **Step 1: Update `_expected_pick` and `simulate_board_at_pick`**

In `backend/analysis.py`, modify `_expected_pick` (currently lines 126-138):

```python
def _expected_pick(player: dict, espn_rankings: dict = None) -> int:
    # Real ADP overall-pick data (where we have it) reflects actual draft
    # order more accurately than the hand-curated tier rank - the two
    # diverge meaningfully for some players (e.g. Ashton Jeanty is rank 15
    # in the hand-curated tiers but ADP has him going 10th overall). Prefer
    # ADP when present, then ESPN's own live-synced PPR rank (refreshes
    # automatically on every sync), then the handful of known-bad rank
    # overrides, then finally the raw hand-curated rank as a last resort.
    if "adp_pick_overall" in player:
        return player["adp_pick_overall"]
    if espn_rankings and player["name"] in espn_rankings:
        return espn_rankings[player["name"]]
    if player["name"] in _EXPECTED_PICK_OVERRIDES:
        return _EXPECTED_PICK_OVERRIDES[player["name"]]
    return player["rank"]
```

Modify `simulate_board_at_pick` (currently lines 141-163) to accept and thread through the new parameter:

```python
def simulate_board_at_pick(players: list, sim_state: dict, overall_pick: int, espn_rankings: dict = None) -> dict:
    effective_state = dict(sim_state)
    for p in players:
        name = p["name"]
        if name in effective_state:
            continue
        if _expected_pick(p, espn_rankings) <= overall_pick - 1:
            effective_state[name] = "gone"

    recommendation = compute_recommendation(players, effective_state)

    available = [
        p for p in players
        if effective_state.get(p["name"]) not in ("mine", "gone")
    ]
    available.sort(key=lambda p: _expected_pick(p, espn_rankings))

    return {
        "round": recommendation["round"],
        "counts": recommendation["counts"],
        "scored": recommendation["scored"],
        "available": available[:10],
    }
```

- [ ] **Step 2: Read the cached rankings in `_simulator_state_payload`**

In `backend/main.py`, modify `_simulator_state_payload` (currently lines 138-160):

```python
def _simulator_state_payload():
    slot = (db.get_cache("sim_slot") or {"data": None})["data"]
    if slot is None:
        return {"slot": None, "picks": [], "current_pick_index": 0, "roster": [], "projection": None}

    sim_state = (db.get_cache("sim_draft_state") or {"data": {}})["data"]
    pick_index = (db.get_cache("sim_pick_index") or {"data": 0})["data"]
    espn_rankings = (db.get_cache("espn_rankings") or {"data": {}})["data"]
    picks = analysis.snake_pick_numbers(slot)
    roster = list(sim_state.keys())

    if pick_index >= len(picks):
        projection = None
    else:
        overall_pick = picks[pick_index]
        projection = analysis.simulate_board_at_pick(
            players_data.PLAYERS, sim_state, overall_pick, espn_rankings
        )

    return {
        "slot": slot,
        "picks": picks,
        "current_pick_index": pick_index,
        "roster": roster,
        "projection": projection,
    }
```

- [ ] **Step 3: Verify manually**

```bash
cd "$HOME/source/repos/EndZone-Intel" && source .venv/Scripts/activate
python3 -c "
from backend.analysis import simulate_board_at_pick
from backend.players import PLAYERS

# without ESPN rankings (old behavior, uses rank fallback)
proj1 = simulate_board_at_pick(PLAYERS, {}, overall_pick=50)
print('without espn_rankings, top available:', proj1['available'][0]['name'])

# with a fake ESPN rankings override to confirm it's actually being read
fake_rankings = {proj1['available'][0]['name']: 5}
proj2 = simulate_board_at_pick(PLAYERS, {}, overall_pick=50, espn_rankings=fake_rankings)
names2 = [p['name'] for p in proj2['available']]
print('with fake low espn rank for that player, still in top pool:', proj1['available'][0]['name'] in names2)
"
```
Expected: the second call doesn't error, confirming the parameter threads through correctly (the specific ordering effect is secondary to confirming no crash and no regression from the no-rankings case).

Then via the live server:
```bash
uvicorn backend.main:app --port 8000
```
```bash
curl -s -X POST http://127.0.0.1:8000/api/sync
curl -s -X POST http://127.0.0.1:8000/api/simulator/reset
curl -s -X POST http://127.0.0.1:8000/api/simulator/start -H "Content-Type: application/json" -d '{"slot": 1}' -o /dev/null -w "%{http_code}\n"
curl -s -X POST http://127.0.0.1:8000/api/simulator/reset -o /dev/null -w "%{http_code}\n"
```
Expected: both calls return 200, no error — confirms the simulator endpoints work end-to-end with `espn_rankings` now being read and passed through.

- [ ] **Step 4: Commit**

```bash
git add backend/analysis.py backend/main.py
git commit -m "Thread ESPN's live rank data into the simulator's expected-pick fallback"
```

---

### Task 5: Bye-week collision warnings — backend

**Files:**
- Create: `backend/bye_weeks.py`
- Modify: `backend/analysis.py`
- Modify: `backend/main.py`

**Interfaces:**
- Produces: `BYE_WEEKS: dict[str, int]` (team abbreviation -> bye week, `backend/bye_weeks.py`)
- Produces: `analysis.bye_week_collisions(roster_players: list, bye_weeks: dict, threshold: int = 3) -> list`, each result `{"week": int, "players": [str, ...]}`
- Produces: `GET /api/analysis/bye-weeks`
- Modifies: `_simulator_state_payload()` to include a `bye_warnings` key

- [ ] **Step 1: Create the bye-week table**

Create `backend/bye_weeks.py`:

```python
"""2026 NFL bye weeks by team abbreviation.

Researched via web search on 2026-07-13 (cross-checked against two
independent sources, consistent on the Week 11 six-team breakdown).
Spot-check against ESPN or NFL.com before fully trusting this on draft
day - schedules are occasionally revised after initial release.
"""

BYE_WEEKS = {
    "KC": 5, "CAR": 5,
    "MIA": 6, "CIN": 6, "DET": 6, "MIN": 6,
    "BUF": 7, "LAC": 7, "WSH": 7, "JAX": 7,
    "NYG": 8, "NO": 8, "SF": 8, "HOU": 8,
    "TEN": 9, "PIT": 9,
    "DEN": 10, "PHI": 10, "CHI": 10, "TB": 10,
    "NE": 11, "CLE": 11, "SEA": 11, "GB": 11, "ATL": 11, "LAR": 11,
    "IND": 13, "NYJ": 13, "LV": 13, "BAL": 13,
    "DAL": 14, "ARI": 14,
}
```

- [ ] **Step 2: Add the collision-detection function**

Append to `backend/analysis.py`:

```python
def bye_week_collisions(roster_players: list, bye_weeks: dict, threshold: int = 3) -> list:
    by_week = {}
    for p in roster_players:
        team = p.get("pro_team") or p.get("team")
        week = bye_weeks.get(team)
        if week is None:
            continue
        by_week.setdefault(week, []).append(p["name"])

    return [
        {"week": week, "players": names}
        for week, names in sorted(by_week.items())
        if len(names) >= threshold
    ]
```

- [ ] **Step 3: Add the endpoint and wire into the simulator payload**

In `backend/main.py`, add near the top imports:

```python
from .bye_weeks import BYE_WEEKS
```

Add after `free_agent_matches_endpoint`:

```python
@app.get("/api/analysis/bye-weeks")
def bye_weeks_endpoint():
    cached = db.get_cache("roster")
    if cached is None:
        return {"data": []}
    return {"data": analysis.bye_week_collisions(cached["data"].get("players", []), BYE_WEEKS)}
```

Modify `_simulator_state_payload` (already touched in Task 4 - add to the existing function):

```python
def _simulator_state_payload():
    slot = (db.get_cache("sim_slot") or {"data": None})["data"]
    if slot is None:
        return {"slot": None, "picks": [], "current_pick_index": 0, "roster": [], "projection": None, "bye_warnings": []}

    sim_state = (db.get_cache("sim_draft_state") or {"data": {}})["data"]
    pick_index = (db.get_cache("sim_pick_index") or {"data": 0})["data"]
    espn_rankings = (db.get_cache("espn_rankings") or {"data": {}})["data"]
    picks = analysis.snake_pick_numbers(slot)
    roster = list(sim_state.keys())

    by_name = {p["name"]: p for p in players_data.PLAYERS}
    roster_players = [by_name[name] for name in roster if name in by_name]
    bye_warnings = analysis.bye_week_collisions(roster_players, BYE_WEEKS)

    if pick_index >= len(picks):
        projection = None
    else:
        overall_pick = picks[pick_index]
        projection = analysis.simulate_board_at_pick(
            players_data.PLAYERS, sim_state, overall_pick, espn_rankings
        )

    return {
        "slot": slot,
        "picks": picks,
        "current_pick_index": pick_index,
        "roster": roster,
        "projection": projection,
        "bye_warnings": bye_warnings,
    }
```

Note: this reuses `bye_week_collisions`, but the simulated roster's player dicts come from `players_data.PLAYERS` (which use a `"team"` key), while `get_roster()`'s real ESPN data uses `"pro_team"` — `bye_week_collisions` already checks both (`p.get("pro_team") or p.get("team")`) to handle this, so no extra branching is needed here.

- [ ] **Step 4: Verify manually**

```bash
cd "$HOME/source/repos/EndZone-Intel" && source .venv/Scripts/activate
python3 -c "
from backend.analysis import bye_week_collisions
from backend.bye_weeks import BYE_WEEKS

roster = [
    {'name': 'Player A', 'pro_team': 'KC'},
    {'name': 'Player B', 'pro_team': 'CAR'},
    {'name': 'Player C', 'pro_team': 'KC'},
    {'name': 'Player D', 'pro_team': 'DET'},
]
print(bye_week_collisions(roster, BYE_WEEKS, threshold=2))
"
```
Expected: `[{'week': 5, 'players': ['Player A', 'Player B', 'Player C']}]` (3 players share week 5's bye - KC and CAR are both week 5 per the table; Player D alone on week 6 doesn't meet the threshold of 2).

Then via the live server:
```bash
uvicorn backend.main:app --port 8000
```
```bash
curl -s http://127.0.0.1:8000/api/analysis/bye-weeks
curl -s -X POST http://127.0.0.1:8000/api/simulator/reset
curl -s -X POST http://127.0.0.1:8000/api/simulator/start -H "Content-Type: application/json" -d '{"slot": 1}' | python3 -c "import json,sys; d=json.load(sys.stdin); print('bye_warnings' in d, d['bye_warnings'])"
curl -s -X POST http://127.0.0.1:8000/api/simulator/reset -o /dev/null -w "%{http_code}\n"
```
Expected: `bye-weeks` returns `{"data": []}` (pre-draft, empty roster); simulator's `bye_warnings` key is present and an empty list at pick 1 (no picks made yet).

- [ ] **Step 5: Commit**

```bash
git add backend/bye_weeks.py backend/analysis.py backend/main.py
git commit -m "Add bye-week collision detection for real and simulated rosters"
```

---

### Task 6: Bye-week collision warnings — frontend

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/simulator.js`
- Modify: `frontend/styles.css`

**Interfaces:**
- Consumes: `GET /api/analysis/bye-weeks` (Task 5), `bye_warnings` key on simulator state (Task 5)

- [ ] **Step 1: Add a Bye-Week Warnings card to the Dashboard**

In `frontend/index.html`, add after the `free-agent-matches-card` section (currently lines 52-55), still inside the dashboard `<div class="grid">`:

```html
    <section class="card" id="bye-weeks-card">
      <h2>Bye Week Collisions</h2>
      <div class="card-body" id="bye-weeks-body">Loading…</div>
    </section>
```

- [ ] **Step 2: Add the render function and wire it into `SECTIONS`**

Add to `frontend/app.js`, after `renderFreeAgentMatches`:

```javascript
function renderByeWeeks(data) {
  if (data.length === 0) {
    setBody('bye-weeks-body', emptyState('No bye-week collisions on your roster.'));
    return;
  }
  const rows = data
    .map((w) => `<li>Week ${w.week}: ${w.players.join(', ')}</li>`)
    .join('');
  setBody('bye-weeks-body', `<ul class="bye-week-list">${rows}</ul>`);
}
```

Add `{ key: 'bye-weeks', path: '/api/analysis/bye-weeks', render: renderByeWeeks }` to the `SECTIONS` array (currently lines 157-164).

- [ ] **Step 3: Add the warning line to the Draft Simulator**

Modify `renderSimBoard` in `frontend/simulator.js` (currently lines 25-101) to render `simState.bye_warnings` under the roster line. Add right after the `rosterEl.textContent = ...` block (currently lines 37-40):

```javascript
  const byeWarningEl = document.getElementById('sim-bye-warnings');
  if (simState.bye_warnings && simState.bye_warnings.length > 0) {
    byeWarningEl.textContent = simState.bye_warnings
      .map((w) => `Week ${w.week}: ${w.players.join(', ')}`)
      .join(' · ');
    byeWarningEl.classList.remove('hidden');
  } else {
    byeWarningEl.classList.add('hidden');
  }
```

In `frontend/index.html`, add the `sim-bye-warnings` element right after `<div class="sim-roster" id="sim-roster"></div>` (currently line 113):

```html
      <div class="sim-bye-warnings hidden" id="sim-bye-warnings"></div>
```

- [ ] **Step 4: Add CSS**

Append to `frontend/styles.css`:

```css
.bye-week-list { margin: 0; padding-left: 1.2rem; color: var(--danger); font-size: 0.85rem; }

.sim-bye-warnings {
  margin: 0 2rem 1rem;
  padding: 0.5rem 0.75rem;
  background: rgba(255,107,107,0.1);
  border: 1px solid rgba(255,107,107,0.3);
  border-radius: 6px;
  color: var(--danger);
  font-size: 0.8rem;
}

.sim-bye-warnings.hidden { display: none; }
```

- [ ] **Step 5: Syntax-check and verify in a browser**

```bash
cd "$HOME/source/repos/EndZone-Intel/frontend" && node --check app.js && node --check simulator.js
```
Then in the browser: Dashboard shows the new "Bye Week Collisions" card (empty state pre-draft). In the Draft Simulator, pick several players from the same bye-week group (e.g. multiple KC/CAR players, both Week 5 per the table) and confirm the warning line appears once 3+ are on the same week.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html frontend/app.js frontend/simulator.js frontend/styles.css
git commit -m "Add bye-week collision warnings to Dashboard and Draft Simulator"
```

---

### Task 7: Weekly opponent info — backend

**Files:**
- Modify: `backend/espn_client.py`
- Modify: `backend/sync.py`

**Interfaces:**
- Produces: `LeagueProvider.get_weekly_matchups(week: int = 1) -> dict` (abstract + `ESPNProvider`), returning `{team_abbr: opponent_abbr}`
- Adds `"week1_matchups"` as a sync job

- [ ] **Step 1: Add the abstract method and implementation**

Add to `LeagueProvider`:

```python
    @abstractmethod
    def get_weekly_matchups(self, week: int = 1) -> dict:
        ...
```

Add to `ESPNProvider`. Requires `from espn_api.football.constant import PRO_TEAM_MAP` added to the imports at the top of `backend/espn_client.py` (inside the `ESPNProvider.__init__` local import block, alongside `from espn_api.football import League`, or as a top-level import — top-level is fine since this module is only imported when the app already depends on `espn_api`):

```python
    def get_weekly_matchups(self, week: int = 1) -> dict:
        schedule = self._league._get_pro_schedule(week)
        return {
            PRO_TEAM_MAP[team_id]: PRO_TEAM_MAP[opponent_id]
            for team_id, (opponent_id, _date) in schedule.items()
        }
```

- [ ] **Step 2: Verify the raw method live before wiring into sync**

```bash
cd "$HOME/source/repos/EndZone-Intel" && source .venv/Scripts/activate
python3 -c "
from backend.espn_client import build_provider
provider = build_provider()
matchups = provider.get_weekly_matchups(week=1)
print('teams with a week 1 matchup:', len(matchups))
print('sample:', list(matchups.items())[:5])
"
```
Expected: up to 32 entries (one per NFL team), each mapping to their Week 1 opponent's abbreviation, no exception. If this errors (e.g. `_get_pro_schedule` needs the league's players/teams fetched first), call `provider._league.fetch_league()` before this check and note that the sync job needs it too, or verify a full `refresh()` isn't required by checking whether `build_provider()` already triggers it on construction (`League.__init__` calls `fetch_league` by default per the library, so this should already be populated).

- [ ] **Step 3: Wire into sync**

In `backend/sync.py`, add to the `jobs` tuple (already modified in Task 3):

```python
    jobs = (
        ("roster", lambda: provider.get_roster(team_id)),
        ("standings", lambda: provider.get_standings()),
        ("matchups", lambda: provider.get_matchups()),
        ("transactions", lambda: provider.get_transactions()),
        ("free_agents", lambda: provider.get_free_agents()),
        ("espn_rankings", lambda: provider.get_espn_rankings()),
        ("week1_matchups", lambda: provider.get_weekly_matchups(week=1)),
    )
```

- [ ] **Step 4: Verify via the running server**

```bash
uvicorn backend.main:app --port 8000
```
```bash
curl -s -X POST http://127.0.0.1:8000/api/sync
```
Expected: `"week1_matchups":"ok"` in the `synced` object.

- [ ] **Step 5: Commit**

```bash
git add backend/espn_client.py backend/sync.py
git commit -m "Add weekly opponent sync from ESPN's own pro team schedule"
```

---

### Task 8: Weekly opponent info — frontend

**Files:**
- Modify: `backend/main.py`
- Modify: `frontend/draftboard.js`
- Modify: `frontend/simulator.js`
- Modify: `frontend/app.js`

**Interfaces:**
- Consumes: cached `"week1_matchups"` dict (Task 7)
- Modifies: `_players_payload()` and `_simulator_state_payload()` to merge opponent info per player

- [ ] **Step 1: Merge opponent info into the players payload**

In `backend/main.py`, modify `_players_payload` (currently lines 71-75):

```python
def _players_payload():
    draft_state = (db.get_cache("draft_state") or {"data": {}})["data"]
    week1_matchups = (db.get_cache("week1_matchups") or {"data": {}})["data"]
    merged = [
        {**p, "state": draft_state.get(p["name"], "available"), "week1_opponent": week1_matchups.get(p["team"])}
        for p in players_data.PLAYERS
    ]
    recommendation = analysis.compute_recommendation(players_data.PLAYERS, draft_state)
    return {"players": merged, "recommendation": recommendation}
```

- [ ] **Step 2: Merge opponent info into the simulator payload**

Modify `_simulator_state_payload` (already touched in Tasks 4 and 5) to also read `week1_matchups` and attach `week1_opponent` to each `available` player. Since `simulate_board_at_pick`'s `available` list comes from `analysis.py` (which shouldn't take on ESPN-specific concerns like opponent lookups - that's presentation, not projection logic), do the merge in `main.py` after calling `simulate_board_at_pick`:

```python
def _simulator_state_payload():
    slot = (db.get_cache("sim_slot") or {"data": None})["data"]
    if slot is None:
        return {"slot": None, "picks": [], "current_pick_index": 0, "roster": [], "projection": None, "bye_warnings": []}

    sim_state = (db.get_cache("sim_draft_state") or {"data": {}})["data"]
    pick_index = (db.get_cache("sim_pick_index") or {"data": 0})["data"]
    espn_rankings = (db.get_cache("espn_rankings") or {"data": {}})["data"]
    week1_matchups = (db.get_cache("week1_matchups") or {"data": {}})["data"]
    picks = analysis.snake_pick_numbers(slot)
    roster = list(sim_state.keys())

    by_name = {p["name"]: p for p in players_data.PLAYERS}
    roster_players = [by_name[name] for name in roster if name in by_name]
    bye_warnings = analysis.bye_week_collisions(roster_players, BYE_WEEKS)

    if pick_index >= len(picks):
        projection = None
    else:
        overall_pick = picks[pick_index]
        projection = analysis.simulate_board_at_pick(
            players_data.PLAYERS, sim_state, overall_pick, espn_rankings
        )
        if projection:
            for p in projection["available"]:
                p["week1_opponent"] = week1_matchups.get(p["team"])

    return {
        "slot": slot,
        "picks": picks,
        "current_pick_index": pick_index,
        "roster": roster,
        "projection": projection,
        "bye_warnings": bye_warnings,
    }
```

- [ ] **Step 3: Show it in the Draft Board's player rows**

Modify `renderDbList` in `frontend/draftboard.js` (currently lines 41-96) — in the row template (currently lines 72-81), add the opponent tag next to the team abbreviation:

```javascript
      html += `
        <div class="db-row ${rowClass}" data-name="${encodeURIComponent(p.name)}">
          <div class="db-rank">${p.rank}</div>
          <div>
            <div class="db-name">${star}${p.name}</div>
            <div class="db-meta">${p.team}${p.week1_opponent ? ` vs. ${p.week1_opponent}` : ''}</div>
          </div>
          <div><span class="db-pos-badge">${p.pos === 'DST' ? 'D/ST' : p.pos}</span> ${flags}</div>
          <button class="db-draft-btn">${btnLabel}</button>
        </div>`;
```

- [ ] **Step 4: Show it in the Simulator's available list**

Modify the row template in `renderSimBoard` in `frontend/simulator.js` (currently lines 72-84) the same way:

```javascript
        (p) => `
        <div class="db-row" data-name="${encodeURIComponent(p.name)}">
          <div class="db-rank">${p.rank}</div>
          <div>
            <div class="db-name">${p.name}</div>
            <div class="db-meta">${p.team}${p.week1_opponent ? ` vs. ${p.week1_opponent}` : ''}</div>
          </div>
          <div><span class="db-pos-badge">${p.pos === 'DST' ? 'D/ST' : p.pos}</span></div>
          <button class="db-draft-btn">Pick</button>
        </div>`
```

- [ ] **Step 5: Syntax-check and verify end-to-end**

```bash
cd "$HOME/source/repos/EndZone-Intel/frontend" && node --check draftboard.js && node --check simulator.js
```
Restart the server, sync, then in the browser: Draft Board rows show "vs. XXX" next to the team when opponent data is present; step through the Draft Simulator and confirm the same on its available list.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py frontend/draftboard.js frontend/simulator.js
git commit -m "Show Week 1 opponent on Draft Board and Simulator player rows"
```

---

## Final Verification

After all 8 tasks are committed:

1. Restart the server fresh: `uvicorn backend.main:app --port 8000` from the repo root (venv active).
2. Run a full sync (`curl -s -X POST http://127.0.0.1:8000/api/sync`) and confirm all 7 jobs report `"ok"` (`roster`, `standings`, `matchups`, `transactions`, `free_agents`, `espn_rankings`, `week1_matchups`).
3. In a browser: exercise every existing feature (Draft Board, Live Draft Mode, Playbook, Draft Simulator) to confirm nothing regressed, then specifically check all 4 new additions: News button on a rostered player, Bye Week Collisions card, opponent tags on Draft Board rows, and simulate several rounds in the Draft Simulator to see the ESPN-rank fallback and bye-week warning working together.
4. Confirm `git log --oneline -9` shows all 8 task commits plus the design spec commit, all on `claude/endzone-intel-phase-1-jaai5i`.
5. Push the branch once everything checks out.
