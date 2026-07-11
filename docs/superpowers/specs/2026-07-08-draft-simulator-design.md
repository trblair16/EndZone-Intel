# Pick-Position Draft Simulator — Design

## Context

The Draft Board (Phase 2, see `2026-07-08-player-analysis-design.md`) already
supports live drafting: mark players mine/gone/available, get a round-based
position-need recommendation via `analysis.compute_recommendation`. That's
useful *during* a draft, but it answers "what do I need right now," not "if
I'm picking Nth, what will my roster look like by the time I'm on the clock
again."

This spec is the pick-position simulator called out as future work in the
player-analysis design's Non-Goals: given a draft slot, project the exact
overall pick numbers a 12-team snake draft hands you, and preview a
plausible queue at each one — before the live draft even starts.

## Goals

- Given a draft slot (1-12), compute the full list of overall pick numbers
  across all 16 rounds using standard snake-draft order.
- For each of those picks, project a "board state" (which ranked players are
  plausibly already gone) using a simple consensus-rank depletion model, and
  surface a recommended pick using the existing `compute_recommendation`
  engine against that projected state.
- Let the user step through the mock draft — accept the suggestion or
  manually swap in a different available player — building a simulated
  roster, independent of the live draft-state used during the real draft.
- Let the user re-run/reset the simulation for a different slot without
  touching the real `draft_state` cache key.

## Non-Goals

- Modeling other teams' actual pick behavior (positional bias, ADP runs,
  reaches). The depletion model assumes strict consensus-rank order: pick
  N is gone by the time N rank-ordered players have been taken league-wide.
  This is a known simplification, not a competitive AI opponent.
- Configurable league size / roster settings pulled from ESPN. Stays
  hardcoded to the existing `LEAGUE_SIZE` constant and `POSITION_TARGETS`
  shape from `analysis.py` (10 teams as of 2026-07, subject to change if the
  league grows - update the constant, not this doc, if that happens),
  consistent with the rest of the app today. Pulling real league settings
  from ESPN is tracked separately (original project spec, Phase 3).
- Persisting more than one simulation at a time — starting a new slot
  simulation overwrites the previous one (same "single-user tool" tradeoff
  used elsewhere in this app).
- Any interaction with the live draft-state used on the Draft Board page.
  The simulator is a separate, pre-draft planning tool; it never reads or
  writes the `"draft_state"` cache key.

## Data Model

New cache keys (existing generic `cache` table in `backend/db.py`, no schema
change — same convention as `"draft_state"`):

- `"sim_slot"` — int, the chosen draft slot (1-12). Absent = no simulation
  started.
- `"sim_draft_state"` — dict, identical shape to the live `draft_state`
  (`{"Player Name": "mine" | "gone"}`), but scoped to the simulation only.

## Snake Draft Math (`backend/analysis.py`)

```python
def snake_pick_numbers(slot: int, rounds: int = 16, league_size: int = LEAGUE_SIZE) -> list[int]:
    """Overall pick numbers for a given slot across all rounds, snake order."""
    picks = []
    for round_ in range(1, rounds + 1):
        pick_in_round = slot if round_ % 2 == 1 else league_size - slot + 1
        picks.append((round_ - 1) * league_size + pick_in_round)
    return picks
```

Pure function, no new dependencies — same testing-by-inspection convention
as the rest of `analysis.py`.

## Simulation Step Logic (`backend/analysis.py`)

```python
def simulate_board_at_pick(players: list, sim_state: dict, overall_pick: int) -> dict:
    """What's the recommended position/player at a given overall pick number,
    assuming the top (overall_pick - 1) ranked players (by the existing
    tier/rank ordering) are already off the board?"""
```

- Players already marked `"mine"` in `sim_state` are *mine*, contributing to
  `compute_recommendation`'s position counts exactly like the live draft.
- Players not in `sim_state` but whose `rank <= overall_pick - 1` are treated
  as depleted ("gone") for this projection only — they are **not** written
  back into `sim_state`; the depletion is recomputed fresh each call from
  `overall_pick`, so moving the slider/stepping through picks stays
  deterministic and side-effect-free.
- Reuses `compute_recommendation(players, effective_state)` unchanged, where
  `effective_state` is built in-memory by merging the real `sim_state`
  ("mine" entries only) with the synthetic depletion "gone" entries.
- Returns the same shape `compute_recommendation` already returns
  (`{"round", "counts", "scored"}`), plus `"available"`: the top ~10
  available players by (tier, rank) at that pick, for display.

## User Flow

1. User opens the Draft Simulator page, enters a slot (1-12), clicks "Start".
2. Backend computes all 16 pick numbers for that slot and returns the first
   one's projected board + recommendation.
3. User either clicks a suggested/available player to mark it "mine" in
   `sim_draft_state` and advance to the next pick, or clicks "skip" to
   advance without picking (rare, but keeps the tool from being a hard
   gate).
4. Progress persists in SQLite (`sim_slot` / `sim_draft_state`) so closing
   the tab and coming back resumes where they left off.
5. "Reset simulation" clears both keys and returns to the slot picker.

## API Endpoints (`backend/main.py`)

- `POST /api/simulator/start` — body `{"slot": int}` (1-12, validated).
  Resets `sim_draft_state` to `{}`, sets `sim_slot`, returns the plan for
  pick 1.
- `GET /api/simulator/state` — returns `{"slot": int | null, "picks": [int, ...],
  "current_pick_index": int, "roster": [...], "projection": {...} | null}`.
  `null` slot means no simulation in progress (frontend shows the slot
  picker instead of the board).
- `POST /api/simulator/pick` — body `{"name": str}`; marks `name` "mine" in
  `sim_draft_state`, advances to the next pick number, returns the updated
  state (same shape as `GET /api/simulator/state`).
- `POST /api/simulator/skip` — advances to the next pick number without
  marking anyone "mine".
- `POST /api/simulator/reset` — clears `sim_slot` and `sim_draft_state`.

All five are pure reads/writes against the two cache keys plus the pure
functions above — no ESPN calls, so this page works fully offline exactly
like the existing Draft Board and Playbook pages.

## Frontend

- New page tab: `Draft Simulator` (alongside Dashboard / Draft Board /
  Playbook), same `page-nav` pattern.
- Slot picker: 12 buttons (1-12) or a number input, "Start Simulation".
- Once started: current pick number + round, a compact roster-so-far strip
  (position counts, matching the Draft Board's `db-reco-bars` styling),
  a list of the top available players at this pick (reusing `db-row`-style
  markup from `draftboard.js` where practical), and Pick / Skip actions.
- "Reset simulation" button, same confirm-dialog pattern as the Draft
  Board's "Reset drafted picks".
- New `frontend/simulator.js`, loaded lazily on first tab visit (same
  `loaded` guard pattern as `draftboard.js`/`playbook.js`).

## Error Handling

Consistent with existing convention: no ESPN dependency means no
"not configured" states here. Invalid slot (outside 1-12) is a 400 from
`POST /api/simulator/start` with a friendly message. Calling `/pick` or
`/skip` with no simulation in progress (`sim_slot` unset) is a 400 telling
the user to start one first, rather than a crash.

## Testing

Same convention as the rest of the project (no automated test framework —
deliberate choice per `CLAUDE.md` and the player-analysis spec). Verify
manually: `snake_pick_numbers(5)` should start `[5, 20, 29, 44, ...]` for a
12-team league (round 2 reverses: pick 20 = (2-1)*12 + (12-5+1) = 12+8 = 20,
correct); step through a full mock draft in the browser and confirm the
roster strip and recommendations update sensibly as picks are made.
