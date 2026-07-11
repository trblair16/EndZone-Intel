# Live Draft Auto-Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poll ESPN's live draft feed during an explicit "Live Draft Mode" toggle so opponent/own picks auto-mark on the Draft Board, removing manual click-to-mark bookkeeping during the actual live draft.

**Architecture:** Frontend-driven polling — the browser calls a new `POST /api/draft/live-sync` endpoint every 5 seconds while a toggle is on; the endpoint fetches live picks from ESPN via `espn-api`'s `refresh_draft()`, reconciles them into the existing `draft_state` cache key, and returns the same payload shape `/api/players` already returns. No new backend lifecycle, no background threads.

**Tech Stack:** Python/FastAPI backend (existing), vanilla JS/HTML/CSS frontend (existing), `espn-api`'s `League.refresh_draft()` (already installed, no new dependency).

## Global Constraints

- Player matching between ESPN's live picks and the ported `PLAYERS` dataset is exact `name` string equality only — unmatched picks are silently skipped, no error, no visible indicator.
- No new SQLite table — reuses the existing `cache` table's `"draft_state"` key, the same one manual click-to-mark already writes to.
- Manual click-to-mark must keep working at all times, including while Live Draft Mode is on — ESPN's data simply overwrites on the next poll if the two disagree.
- No automated test framework is introduced (none exists in this project by design). Verification is manual via `curl` and a browser, same as prior phases.
- A failed poll (network blip, ESPN hiccup) must never surface as a JS `alert()` or stop the polling interval — it silently retries on the next 5-second tick.
- `get_live_picks()` against a league that hasn't started its draft must return `[]`, not raise — mirrors the existing `get_matchups()` pre-draft convention in `backend/espn_client.py:87-95`.

---

### Task 1: `get_live_picks` on the ESPN provider

**Files:**
- Modify: `backend/espn_client.py`

**Interfaces:**
- Produces: `LeagueProvider.get_live_picks() -> list[dict]` (abstract method) and `ESPNProvider.get_live_picks()` implementation, each returned dict shaped `{"team_id": int | None, "player_name": str}`

- [ ] **Step 1: Add the abstract method**

In `backend/espn_client.py`, add to the `LeagueProvider` class (after the existing `get_free_agents` abstract method at line 33-34):

```python
    @abstractmethod
    def get_live_picks(self) -> list:
        ...
```

- [ ] **Step 2: Implement it on `ESPNProvider`**

Add to the `ESPNProvider` class, after `get_free_agents` (line 126-127):

```python
    def get_live_picks(self) -> list:
        self._league.refresh_draft(refresh_players=True)
        return [
            {
                "team_id": pick.team.team_id if pick.team else None,
                "player_name": pick.playerName,
            }
            for pick in self._league.draft
        ]
```

- [ ] **Step 3: Verify manually against the current (pre-draft) league state**

From the repo root, with the venv active:
```bash
python -c "
from backend.espn_client import build_provider
provider = build_provider()
print(provider.get_live_picks())
"
```
Expected: prints `[]` — the league hasn't drafted yet, so `refresh_draft()` returns no picks. This confirms the pre-draft path doesn't raise, per the Global Constraints. (Real pick data can only be verified once your actual draft is in progress — that part of this task isn't testable today.)

- [ ] **Step 4: Commit**

```bash
git add backend/espn_client.py
git commit -m "Add get_live_picks to pull ESPN's live draft feed"
```

---

### Task 2: `reconcile_live_picks` analysis function

**Files:**
- Modify: `backend/analysis.py`

**Interfaces:**
- Consumes: `PLAYERS` shape from `backend/players.py` (`name` key used for matching); live picks shape from Task 1 (`{"team_id", "player_name"}`)
- Produces: `reconcile_live_picks(draft_state: dict, live_picks: list, players: list, my_team_id: int | None) -> dict` — returns a **new** dict (does not mutate `draft_state`), matching the existing non-mutating convention used by `cycle_draft_state`

- [ ] **Step 1: Write the function**

Append to `backend/analysis.py`:

```python
def reconcile_live_picks(draft_state: dict, live_picks: list, players: list, my_team_id) -> dict:
    known_names = {p["name"] for p in players}
    updated = dict(draft_state)
    for pick in live_picks:
        name = pick["player_name"]
        if name not in known_names:
            continue
        updated[name] = "mine" if pick["team_id"] == my_team_id else "gone"
    return updated
```

- [ ] **Step 2: Verify manually**

```bash
python -c "
from backend.analysis import reconcile_live_picks
from backend.players import PLAYERS

live_picks = [
    {'team_id': 5, 'player_name': 'Jahmyr Gibbs'},
    {'team_id': 1, 'player_name': 'Bijan Robinson'},
    {'team_id': 1, 'player_name': 'Some Undrafted Rookie Nobody Ported'},
]
result = reconcile_live_picks({}, live_picks, PLAYERS, my_team_id=5)
print(result)
"
```
Expected: `{'Jahmyr Gibbs': 'mine', 'Bijan Robinson': 'gone'}` — the third pick (unmatched name) is silently skipped, not present in the result at all.

- [ ] **Step 3: Verify manual-state overwrite behavior**

```bash
python -c "
from backend.analysis import reconcile_live_picks
from backend.players import PLAYERS

# simulate: user manually (and wrongly) marked Gibbs as 'gone', ESPN then reports it as their own pick
existing_state = {'Jahmyr Gibbs': 'gone'}
live_picks = [{'team_id': 5, 'player_name': 'Jahmyr Gibbs'}]
result = reconcile_live_picks(existing_state, live_picks, PLAYERS, my_team_id=5)
print(result)
"
```
Expected: `{'Jahmyr Gibbs': 'mine'}` — ESPN's live data overwrites the stale manual mark, confirming the self-healing behavior described in the design.

- [ ] **Step 4: Commit**

```bash
git add backend/analysis.py
git commit -m "Add reconcile_live_picks for auto-marking draft state from ESPN"
```

---

### Task 3: `POST /api/draft/live-sync` endpoint

**Files:**
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `provider.get_live_picks()` (Task 1), `analysis.reconcile_live_picks()` (Task 2), `config.team_id_int()` (existing, `backend/config.py:19-20`), `db.get_cache`/`db.set_cache` (existing), `_players_payload()` (existing helper, `backend/main.py:71-75`)
- Produces: `POST /api/draft/live-sync` returning the same shape as `GET /api/players` (`{"players": [...], "recommendation": {...}}`)

- [ ] **Step 1: Add the endpoint**

In `backend/main.py`, add after `reset_draft_state` (after line 98):

```python
@app.post("/api/draft/live-sync")
def live_sync():
    try:
        provider = build_provider()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    live_picks = provider.get_live_picks()
    current = (db.get_cache("draft_state") or {"data": {}})["data"]
    updated = analysis.reconcile_live_picks(
        current, live_picks, players_data.PLAYERS, config.team_id_int()
    )
    db.set_cache("draft_state", updated)
    return _players_payload()
```

- [ ] **Step 2: Restart the server and verify**

```bash
uvicorn backend.main:app --port 8000
```
In another terminal:
```bash
curl -s -X POST http://127.0.0.1:8000/api/draft/live-sync | head -c 300
```
Expected: `{"players":[...],"recommendation":{...}}` — same shape as `/api/players`, no 500, since pre-draft this is a safe no-op (empty live picks list, `draft_state` unchanged except for whatever manual marks already existed).

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "Add POST /api/draft/live-sync endpoint"
```

---

### Task 4: Frontend — Live Draft Mode toggle and polling

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/styles.css`
- Modify: `frontend/draftboard.js`

**Interfaces:**
- Consumes: `POST /api/draft/live-sync` (Task 3)

- [ ] **Step 1: Add the toggle button and status line to the Draft Board controls**

In `frontend/index.html`, inside `<div class="db-controls">`, add these two elements right after the closing `</button>` of `#db-hide-drafted` (and before the closing `</div>` of `db-controls`):

```html
      <button class="db-toggle" id="db-live-toggle">Live Draft Mode</button>
      <span class="db-live-status" id="db-live-status"></span>
```

- [ ] **Step 2: Add CSS for the status line**

Append to `frontend/styles.css`:

```css
.db-live-status {
  font-size: 0.75rem;
  color: var(--chalk-dim);
  align-self: center;
}
```

- [ ] **Step 3: Add polling state and toggle logic to `draftboard.js`**

Add near the top of `frontend/draftboard.js`, alongside the other `let db*` state variables:

```javascript
let dbLiveInterval = null;
let dbLiveOn = false;
```

Add these functions (place them after `markDraftState`, before `loadDraftBoard`):

```javascript
async function pollLiveDraft() {
  const statusEl = document.getElementById('db-live-status');
  try {
    const res = await fetch('/api/draft/live-sync', { method: 'POST' });
    if (!res.ok) throw new Error(`status ${res.status}`);
    const body = await res.json();
    dbPlayers = body.players;
    dbRecommendation = body.recommendation;
    renderDbRecommendation();
    renderDbList();
    statusEl.textContent = 'Live Draft Mode: ON — last synced just now';
  } catch (err) {
    statusEl.textContent = 'Live Draft Mode: ON — sync issue, retrying...';
  }
}

function setLiveDraftMode(on) {
  dbLiveOn = on;
  const btn = document.getElementById('db-live-toggle');
  const statusEl = document.getElementById('db-live-status');
  btn.classList.toggle('active', on);
  if (on) {
    pollLiveDraft();
    dbLiveInterval = setInterval(pollLiveDraft, 5000);
  } else {
    clearInterval(dbLiveInterval);
    dbLiveInterval = null;
    statusEl.textContent = '';
  }
}
```

- [ ] **Step 4: Wire up the toggle button's click handler**

Add at the bottom of `frontend/draftboard.js`, alongside the other `document.getElementById(...).addEventListener(...)` calls:

```javascript
document.getElementById('db-live-toggle').addEventListener('click', () => {
  setLiveDraftMode(!dbLiveOn);
});
```

- [ ] **Step 5: Syntax-check the modified file**

```bash
node --check frontend/draftboard.js
```
Expected: no output (success).

- [ ] **Step 6: Verify in a browser**

Start the server (`uvicorn backend.main:app --port 8000` from repo root, venv active), open `http://127.0.0.1:8000`, go to the Draft Board tab. Click "Live Draft Mode". Confirm:
- The button visually toggles to an active state
- The status line shows "Live Draft Mode: ON — last synced just now" within a moment
- The status line keeps updating roughly every 5 seconds
- Clicking a player to manually mark them still works while Live Draft Mode is on
- Clicking "Live Draft Mode" again turns it off and clears the status line

Since the league hasn't drafted yet, the board itself won't visibly change from polling (ESPN has no picks to report) — this step confirms the polling loop runs cleanly end-to-end without erroring, not that live picks display correctly (that can only be confirmed on draft day, per the Global Constraints).

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html frontend/styles.css frontend/draftboard.js
git commit -m "Add Live Draft Mode toggle with 5s auto-sync polling"
```

---

## Final Verification

After all 4 tasks are committed:

1. Restart the server fresh: `uvicorn backend.main:app --port 8000` from the repo root (venv active).
2. Run `curl -s -X POST http://127.0.0.1:8000/api/draft/live-sync` — confirm no 500, response shape matches `/api/players`.
3. In the browser, exercise the full Draft Board: search/filter, manual mark, Live Draft Mode toggle on/off, reset — confirm nothing regressed from before this feature was added.
4. Confirm `git log --oneline -6` shows all 4 task commits plus the design spec commit, all on `claude/endzone-intel-phase-1-jaai5i`.
5. **Reminder for draft day:** turn Live Draft Mode on once your actual draft begins, and watch the first couple of opponent picks to confirm they auto-mark correctly before relying on it fully. Manual click-to-mark is always available as a fallback if a name doesn't match.
