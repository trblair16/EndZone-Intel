# Pick-Position Draft Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick a draft slot (1-10) and step through a projected mock draft — pick-by-pick, using a consensus-rank depletion model plus the existing recommendation engine — entirely separate from the live Draft Board's draft state.

**Architecture:** Two new pure functions in `backend/analysis.py` (snake-draft pick math, per-pick board projection), two new cache keys (`sim_slot`, `sim_draft_state`) reusing the existing generic `cache` table, five new endpoints in `backend/main.py`, and a new `Draft Simulator` page/tab following the same lazy-load pattern as `draftboard.js`/`playbook.js`.

**Tech Stack:** Python/FastAPI backend (existing), vanilla JS/HTML/CSS frontend (existing), SQLite cache (existing) — no new dependencies.

## Global Constraints

- League size is 10 as of 2026-07-11 (see `backend/analysis.py`'s `LEAGUE_SIZE` constant) — subject to change if more people join; all snake-draft math must read `LEAGUE_SIZE` from `analysis.py` rather than hardcoding a number, so a future league-size change only requires editing one constant.
- The simulator never reads or writes the `"draft_state"` cache key used by the live Draft Board / Live Draft Mode — it uses its own `"sim_slot"` and `"sim_draft_state"` keys exclusively.
- The depletion model assumes strict consensus-rank order (top N ranked players are gone by overall pick N) — this is a known simplification, not a real opponent-behavior model. Don't add opponent modeling in this plan.
- No automated test framework is introduced (none exists in this project by design). Verification is manual, via `curl` and a browser, same as prior phases.
- Rounds are capped at 16 (`min(16, ...)`), matching the existing convention in `compute_recommendation`.

---

### Task 1: Snake-draft pick math

**Files:**
- Modify: `backend/analysis.py`

**Interfaces:**
- Produces: `snake_pick_numbers(slot: int, rounds: int = 16, league_size: int = LEAGUE_SIZE) -> list[int]`

- [ ] **Step 1: Write the function**

Append to `backend/analysis.py` (after `reconcile_live_picks`, at the end of the file):

```python
def snake_pick_numbers(slot: int, rounds: int = 16, league_size: int = LEAGUE_SIZE) -> list:
    picks = []
    for round_ in range(1, rounds + 1):
        pick_in_round = slot if round_ % 2 == 1 else league_size - slot + 1
        picks.append((round_ - 1) * league_size + pick_in_round)
    return picks
```

- [ ] **Step 2: Verify manually**

```bash
cd "$HOME/source/repos/EndZone-Intel" && source .venv/Scripts/activate
python -c "
from backend.analysis import snake_pick_numbers
picks = snake_pick_numbers(5)
print(picks[:4])
print(len(picks))
"
```
Expected: with `LEAGUE_SIZE = 10`, slot 5 gives `[5, 16, 25, 36]` (round 1: pick 5; round 2 reverses: `10 - 5 + 1 = 6`th pick of round 2 = `10 + 6 = 16`; round 3: pick 5 again = `20 + 5 = 25`; round 4 reverses again = `30 + 6 = 36`), and `len(picks) == 16`.

- [ ] **Step 3: Commit**

```bash
git add backend/analysis.py
git commit -m "Add snake-draft pick number math for the draft simulator"
```

---

### Task 2: Per-pick board projection

**Files:**
- Modify: `backend/analysis.py`

**Interfaces:**
- Consumes: `PLAYERS` shape (`name`, `pos`, `tier`, `rank`); `compute_recommendation` (existing, Task from Piece A)
- Produces: `simulate_board_at_pick(players: list, sim_state: dict, overall_pick: int) -> dict` returning `{"round", "counts", "scored", "available"}` — the first three keys identical in shape to `compute_recommendation`'s return value, plus `"available"`: the top 10 non-depleted, non-"mine" players sorted by `(tier, rank)`

- [ ] **Step 1: Write the function**

Append to `backend/analysis.py`:

```python
def simulate_board_at_pick(players: list, sim_state: dict, overall_pick: int) -> dict:
    effective_state = dict(sim_state)
    for p in players:
        name = p["name"]
        if name in effective_state:
            continue
        if p["rank"] <= overall_pick - 1:
            effective_state[name] = "gone"

    recommendation = compute_recommendation(players, effective_state)

    available = [
        p for p in players
        if effective_state.get(p["name"]) not in ("mine", "gone")
    ]
    available.sort(key=lambda p: (p["tier"], p["rank"]))

    return {
        "round": recommendation["round"],
        "counts": recommendation["counts"],
        "scored": recommendation["scored"],
        "available": available[:10],
    }
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from backend.analysis import simulate_board_at_pick
from backend.players import PLAYERS

# pick 1: nobody depleted yet, top of the board should be rank 1
result = simulate_board_at_pick(PLAYERS, {}, overall_pick=1)
print('pick 1 top available:', result['available'][0]['name'], result['available'][0]['rank'])

# pick 15: top 14 ranked players assumed gone
result2 = simulate_board_at_pick(PLAYERS, {}, overall_pick=15)
print('pick 15 top available rank:', result2['available'][0]['rank'])

# sim_state 'mine' entries should count toward position needs, not show as available
result3 = simulate_board_at_pick(PLAYERS, {'Jahmyr Gibbs': 'mine'}, overall_pick=1)
print('pick 1 with Gibbs mine - RB count:', result3['counts']['RB'])
print('Gibbs in available list:', any(p['name'] == 'Jahmyr Gibbs' for p in result3['available']))
"
```
Expected: pick 1 shows the rank-1 player as top available; pick 15 shows a player ranked 15 or higher (since ranks 1-14 are depleted, and rank values are unique per the earlier dedup fix); with Gibbs marked "mine", RB count is `1` and Gibbs does not appear in the available list.

- [ ] **Step 3: Commit**

```bash
git add backend/analysis.py
git commit -m "Add simulate_board_at_pick for consensus-rank draft projection"
```

---

### Task 3: Simulator API endpoints

**Files:**
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `analysis.snake_pick_numbers`, `analysis.simulate_board_at_pick` (Tasks 1-2); `db.get_cache`/`db.set_cache` (existing)
- Produces: `POST /api/simulator/start`, `GET /api/simulator/state`, `POST /api/simulator/pick`, `POST /api/simulator/skip`, `POST /api/simulator/reset`

- [ ] **Step 1: Add a shared helper and the start/state endpoints**

Progress through the 16 simulated picks is tracked by a dedicated
`"sim_pick_index"` cache key (an `int`, incremented on both pick and skip),
kept separate from `"sim_draft_state"` (which only ever holds real
`{player_name: "mine"}` entries — no synthetic placeholder keys).

Add to `backend/main.py`, after the `free_agent_matches_endpoint` function (after line 135) and before the `FRONTEND_DIR` line:

```python
def _simulator_state_payload():
    slot = (db.get_cache("sim_slot") or {"data": None})["data"]
    if slot is None:
        return {"slot": None, "picks": [], "current_pick_index": 0, "roster": [], "projection": None}

    sim_state = (db.get_cache("sim_draft_state") or {"data": {}})["data"]
    pick_index = (db.get_cache("sim_pick_index") or {"data": 0})["data"]
    picks = analysis.snake_pick_numbers(slot)
    roster = list(sim_state.keys())

    if pick_index >= len(picks):
        projection = None
    else:
        overall_pick = picks[pick_index]
        projection = analysis.simulate_board_at_pick(players_data.PLAYERS, sim_state, overall_pick)

    return {
        "slot": slot,
        "picks": picks,
        "current_pick_index": pick_index,
        "roster": roster,
        "projection": projection,
    }


class SimulatorStartRequest(BaseModel):
    slot: int


@app.post("/api/simulator/start")
def simulator_start(body: SimulatorStartRequest):
    if not (1 <= body.slot <= analysis.LEAGUE_SIZE):
        raise HTTPException(
            status_code=400,
            detail=f"Slot must be between 1 and {analysis.LEAGUE_SIZE}.",
        )
    db.set_cache("sim_slot", body.slot)
    db.set_cache("sim_draft_state", {})
    db.set_cache("sim_pick_index", 0)
    return _simulator_state_payload()


@app.get("/api/simulator/state")
def simulator_state():
    return _simulator_state_payload()
```

- [ ] **Step 2: Add the pick/skip/reset endpoints**

Add immediately after `simulator_state`:

```python
class SimulatorPickRequest(BaseModel):
    name: str


@app.post("/api/simulator/pick")
def simulator_pick(body: SimulatorPickRequest):
    slot = (db.get_cache("sim_slot") or {"data": None})["data"]
    if slot is None:
        raise HTTPException(status_code=400, detail="No simulation in progress. Start one first.")

    sim_state = (db.get_cache("sim_draft_state") or {"data": {}})["data"]
    pick_index = (db.get_cache("sim_pick_index") or {"data": 0})["data"]
    updated = dict(sim_state)
    updated[body.name] = "mine"
    db.set_cache("sim_draft_state", updated)
    db.set_cache("sim_pick_index", pick_index + 1)
    return _simulator_state_payload()


@app.post("/api/simulator/skip")
def simulator_skip():
    slot = (db.get_cache("sim_slot") or {"data": None})["data"]
    if slot is None:
        raise HTTPException(status_code=400, detail="No simulation in progress. Start one first.")

    pick_index = (db.get_cache("sim_pick_index") or {"data": 0})["data"]
    db.set_cache("sim_pick_index", pick_index + 1)
    return _simulator_state_payload()


@app.post("/api/simulator/reset")
def simulator_reset():
    db.set_cache("sim_slot", None)
    db.set_cache("sim_draft_state", {})
    db.set_cache("sim_pick_index", 0)
    return _simulator_state_payload()
```

- [ ] **Step 3: Restart the server and verify the full flow**

```bash
uvicorn backend.main:app --port 8000
```
In another terminal:
```bash
curl -s -X POST http://127.0.0.1:8000/api/simulator/start -H "Content-Type: application/json" -d '{"slot": 5}'
curl -s http://127.0.0.1:8000/api/simulator/state | head -c 400
curl -s -X POST http://127.0.0.1:8000/api/simulator/pick -H "Content-Type: application/json" -d '{"name": "Jahmyr Gibbs"}' | head -c 300
curl -s -X POST http://127.0.0.1:8000/api/simulator/skip | head -c 300
curl -s -X POST http://127.0.0.1:8000/api/simulator/reset
curl -s -X POST http://127.0.0.1:8000/api/simulator/pick -H "Content-Type: application/json" -d '{"name": "Test"}'
```
Expected: `start` returns `slot: 5`, `picks` starting `[5, 16, 25, ...]`, `current_pick_index: 0`; after marking Gibbs, `current_pick_index` becomes `1` and `roster` includes `"Jahmyr Gibbs"`; after skip, `current_pick_index` becomes `2`; after reset, `state` shows `slot: null`; the final `pick` call (after reset, no simulation started) returns a 400 with the "Start one first" message, not a crash.

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "Add draft simulator API endpoints"
```

---

### Task 4: Frontend — Draft Simulator page

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Create: `frontend/simulator.js`

**Interfaces:**
- Consumes: `POST /api/simulator/start`, `GET /api/simulator/state`, `POST /api/simulator/pick`, `POST /api/simulator/skip`, `POST /api/simulator/reset` (Task 3)
- Consumes existing globals from `frontend/app.js`: `apiGet`, `emptyState`

- [ ] **Step 1: Add the nav tab and page markup**

In `frontend/index.html`, add a fourth tab to `<nav class="page-nav">` (after the Playbook button):

```html
    <button class="page-tab" data-page="simulator">Draft Simulator</button>
```

Add a new `<main>` block after `page-playbook`'s closing `</main>` and before the `<script src="/app.js">` line:

```html
  <main class="page hidden" id="page-simulator">
    <div id="sim-slot-picker" class="sim-slot-picker">
      <p class="sim-intro">Pick your draft slot to preview a projected board at each of your picks.</p>
      <div class="sim-slot-grid" id="sim-slot-grid"></div>
    </div>

    <div id="sim-board" class="hidden">
      <div class="db-reco">
        <div class="db-reco-top">
          <span class="db-reco-title">Simulated Pick</span>
          <span id="sim-pick-label">Pick 1</span>
        </div>
        <div class="db-reco-bars" id="sim-reco-bars"></div>
      </div>

      <div class="sim-roster" id="sim-roster"></div>

      <div class="db-list" id="sim-available"></div>

      <div class="db-footer">
        <span id="sim-status"></span>
        <div>
          <button class="db-toggle" id="sim-skip">Skip</button>
          <button class="db-reset" id="sim-reset">Reset simulation</button>
        </div>
      </div>
    </div>
  </main>
```

- [ ] **Step 2: Add CSS for the slot picker and roster strip**

Append to `frontend/styles.css`:

```css
.sim-intro { color: var(--chalk-dim); padding: 1rem 2rem 0; font-size: 0.9rem; }

.sim-slot-picker { padding: 1rem 2rem; }

.sim-slot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(60px, 1fr));
  gap: 0.5rem;
  max-width: 500px;
  margin-top: 1rem;
}

.sim-slot-btn {
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(255,183,3,0.2);
  color: var(--chalk);
  padding: 0.75rem;
  font-size: 1rem;
  font-weight: 700;
  border-radius: 6px;
  cursor: pointer;
}

.sim-slot-btn:hover { border-color: var(--amber); color: var(--amber); }

.sim-roster {
  margin: 1rem 2rem;
  padding: 0.75rem 1rem;
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(255,183,3,0.2);
  border-radius: 8px;
  font-size: 0.85rem;
  color: var(--chalk-dim);
}
```

- [ ] **Step 3: Create `frontend/simulator.js`**

```javascript
let simLoaded = false;
let simState = null;

function renderSlotPicker() {
  const grid = document.getElementById('sim-slot-grid');
  let html = '';
  for (let i = 1; i <= 10; i++) {
    html += `<button class="sim-slot-btn" data-slot="${i}">${i}</button>`;
  }
  grid.innerHTML = html;
  grid.querySelectorAll('.sim-slot-btn').forEach((btn) => {
    btn.onclick = async () => {
      const slot = Number(btn.getAttribute('data-slot'));
      const res = await fetch('/api/simulator/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot }),
      });
      simState = await res.json();
      renderSimBoard();
    };
  });
}

function renderSimBoard() {
  const pickerEl = document.getElementById('sim-slot-picker');
  const boardEl = document.getElementById('sim-board');

  if (!simState || simState.slot === null) {
    pickerEl.classList.remove('hidden');
    boardEl.classList.add('hidden');
    return;
  }
  pickerEl.classList.add('hidden');
  boardEl.classList.remove('hidden');

  const rosterEl = document.getElementById('sim-roster');
  rosterEl.textContent = simState.roster.length
    ? `Simulated roster: ${simState.roster.join(', ')}`
    : 'Simulated roster: (no picks yet)';

  const statusEl = document.getElementById('sim-status');

  if (!simState.projection) {
    document.getElementById('sim-pick-label').textContent = 'Simulation complete';
    document.getElementById('sim-reco-bars').innerHTML = '';
    document.getElementById('sim-available').innerHTML = emptyState('All 16 rounds simulated.');
    statusEl.textContent = `${simState.roster.length} picks made`;
    return;
  }

  const overallPick = simState.picks[simState.current_pick_index];
  document.getElementById('sim-pick-label').textContent =
    `Pick ${simState.current_pick_index + 1} of ${simState.picks.length} (overall #${overallPick}, round ${simState.projection.round})`;

  document.getElementById('sim-reco-bars').innerHTML = simState.projection.scored
    .map((s) => {
      const pct = Math.min(100, Math.round((s.count / s.max) * 100));
      const fillClass = s.full ? 'met' : '';
      return `
        <div>
          <div class="db-reco-bar-label"><span>${s.label}</span><span>${s.count}/${s.min}${s.max > s.min ? '-' + s.max : ''}</span></div>
          <div class="db-reco-bar-track"><div class="db-reco-bar-fill ${fillClass}" style="width:${pct}%"></div></div>
        </div>`;
    })
    .join('');

  const availableEl = document.getElementById('sim-available');
  if (simState.projection.available.length === 0) {
    availableEl.innerHTML = emptyState('No players left in the projected pool.');
  } else {
    availableEl.innerHTML = simState.projection.available
      .map(
        (p) => `
        <div class="db-row" data-name="${encodeURIComponent(p.name)}">
          <div class="db-rank">${p.rank}</div>
          <div>
            <div class="db-name">${p.name}</div>
            <div class="db-meta">${p.team}</div>
          </div>
          <div><span class="db-pos-badge">${p.pos === 'DST' ? 'D/ST' : p.pos}</span></div>
          <button class="db-draft-btn">Pick</button>
        </div>`
      )
      .join('');
    availableEl.querySelectorAll('.db-row').forEach((row) => {
      row.onclick = async () => {
        const name = decodeURIComponent(row.getAttribute('data-name'));
        const res = await fetch('/api/simulator/pick', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        });
        simState = await res.json();
        renderSimBoard();
      };
    });
  }

  statusEl.textContent = '';
}

async function loadSimulator() {
  if (simLoaded) return;
  simLoaded = true;
  renderSlotPicker();
  try {
    simState = await apiGet('/api/simulator/state');
    renderSimBoard();
  } catch (err) {
    document.getElementById('sim-board').innerHTML = emptyState(err.message);
  }
}

document.getElementById('sim-skip').addEventListener('click', async () => {
  const res = await fetch('/api/simulator/skip', { method: 'POST' });
  simState = await res.json();
  renderSimBoard();
});

document.getElementById('sim-reset').addEventListener('click', async () => {
  if (!confirm('Reset the simulation and pick a new slot?')) return;
  const res = await fetch('/api/simulator/reset', { method: 'POST' });
  simState = await res.json();
  renderSimBoard();
});
```

- [ ] **Step 4: Add the script tag and wire the page-nav switch**

In `frontend/index.html`, after `<script src="/playbook.js"></script>`, add:
```html
  <script src="/simulator.js"></script>
```

In `frontend/app.js`, modify the existing page-tab click handler (added for the previous feature) to also load the simulator:

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
    if (page === 'simulator') loadSimulator();
  });
});
```

Find this exact block (it already exists from the previous feature) and add only the `if (page === 'simulator') loadSimulator();` line — do not duplicate the whole listener registration.

- [ ] **Step 5: Syntax-check the new/modified JS**

```bash
cd "$HOME/source/repos/EndZone-Intel/frontend"
node --check simulator.js
node --check app.js
```
Expected: no output from either (success).

- [ ] **Step 6: Verify in a browser**

Start the server (`uvicorn backend.main:app --port 8000` from repo root, venv active), open `http://127.0.0.1:8000`, click the "Draft Simulator" tab. Confirm:
- A 10-button slot picker appears (1-10, matching `LEAGUE_SIZE`)
- Clicking a slot (e.g. 5) starts a simulation and shows "Pick 1 of 16 (overall #5, round 1)"
- The top of the available list is the rank-1 player, with position-need bars matching the Draft Board's visual style
- Clicking a player advances to the next pick, updates the roster strip, and re-projects the board (players ranked below the new depletion threshold appear at the top of the available list)
- "Skip" advances the pick counter without adding to the roster
- "Reset simulation" (after confirming) returns to the slot picker
- Switching to the Draft Board tab and back to Draft Simulator preserves progress (since it's stored server-side, not just in JS state)

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html frontend/styles.css frontend/simulator.js frontend/app.js
git commit -m "Add Draft Simulator page with slot picker and pick-by-pick projection"
```

---

## Final Verification

After all 4 tasks are committed:

1. Restart the server fresh: `uvicorn backend.main:app --port 8000` from the repo root (venv active).
2. Run through the full simulator flow via `curl` one more time end-to-end (start slot 3, check state, pick a player, skip, reset) — confirm no 500s anywhere.
3. In the browser, confirm the Draft Board and Live Draft Mode from the prior feature still work unaffected (the simulator must not touch `"draft_state"`).
4. Confirm `git log --oneline -8` shows all 4 task commits plus the design spec and league-size fix commits, all on `claude/endzone-intel-phase-1-jaai5i`.
5. Push the branch once everything checks out.
