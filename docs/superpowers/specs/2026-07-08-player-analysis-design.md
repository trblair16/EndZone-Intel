# Player Analysis & Draft Board — Design

## Context

EndZone Intel (Phase 1) currently mirrors live ESPN league data (roster,
standings, matchups, transactions) with no player-level intelligence layer.
Separately, a standalone Claude-artifact "draft board" already exists: a
self-contained HTML/CSS/JS tool with a hand-curated `PLAYERS` dataset (142
players, tiers 1-7, risk flags, target/watch stars), a round-based
recommendation engine, and a narrative "Season Playbook" of rules derived
from the 2025 season.

This is Piece A of a larger goal (a personal FantasyPros/Walter-Picks-style
tool). Piece A brings the player/playbook data and analysis into EndZone
Intel itself. A follow-up piece (a pick-position draft simulator — "if I
pick at slot N, what's my queue at each of my picks") and weekly
matchup/opponent analysis are explicitly out of scope here and will get
their own specs once this data layer exists.

## Goals

- Port the `PLAYERS` and Season Playbook datasets into the backend as plain
  Python data, editable by hand as news breaks (no external rankings feed).
- Reproduce the draft board's live click-to-mark (Mine/Gone/Available) and
  round-based recommendation inside EndZone Intel, backed by SQLite instead
  of per-browser artifact storage.
- Cross-reference live ESPN data against the player dataset: flag risk-tagged
  players on your actual roster, and surface free agents matching your
  target/watch list.
- Add a static Playbook reference page.

## Non-Goals

- Pick-position draft simulator / "what-if by pick number" (separate spec).
- Weekly matchup/opponent/start-sit analysis (separate spec, Phase 3).
- Automatic rankings/ADP ingestion from an external source.
- Fuzzy name matching between ESPN player names and the ported dataset —
  exact string match only. Revisit only if it actually causes missed matches.

## Data Model

`backend/players.py` (currently an empty placeholder) gains two datasets,
ported from the artifact:

```python
PLAYERS: list[dict] = [
    {"rank": 1, "name": "Jahmyr Gibbs", "pos": "RB", "team": "DET",
     "tier": 1, "flags": [], "target": True, "watch": False},
    ...
]

PLAYBOOK_RULES: list[dict] = [
    {"title": "Cap your transactions", "body": "...", "evidence": "..."},
    ...
]
```

`flags` values match the artifact's vocabulary: `injury`, `committee`,
`breakout`, `rookie`, `scheme`.

## Draft State Persistence

No new table. Reuses the existing generic `cache` table in `backend/db.py`
(key → JSON blob) under a new key, `"draft_state"`:

```json
{"Jahmyr Gibbs": "mine", "Bijan Robinson": "gone"}
```

Players absent from this dict are "available" — same sparse-dict convention
the original artifact used with `window.storage`.

## API Endpoints (`backend/main.py`)

- `GET /api/players` — returns `PLAYERS` merged with current draft state,
  plus a server-side computed recommendation (round, position needs,
  scored suggestions) — a Python port of the artifact's
  `computeRecommendation()`.
- `POST /api/players/draft-state` — body `{"name": str}`; cycles that
  player's state `available → mine → gone → available`; returns the updated
  players + recommendation payload.
- `POST /api/players/reset-draft-state` — clears the draft state cache key.
- `GET /api/playbook` — returns `PLAYBOOK_RULES`.
- `GET /api/analysis/roster-flags` — reads the cached `roster` entry
  (from the existing sync), matches each rostered player by name against
  `PLAYERS`, returns those with a non-empty `flags` list. Empty list (not an
  error) if roster isn't synced yet or has no flagged players.
- `GET /api/analysis/free-agent-matches` — reads a new cached `free_agents`
  entry (see below), matches against `PLAYERS` entries where `target` or
  `watch` is true, returns the matches.

### Sync changes (`backend/sync.py`, `backend/espn_client.py`)

`ESPNProvider.get_free_agents()` already exists on the interface but isn't
called by `run_sync`. Add `"free_agents"` as a fifth sync job so
`free-agent-matches` has data to read. `LeagueProvider.get_free_agents`
already returns serialized player dicts via `_serialize_player`, matching
the shape needed for name-based cross-reference.

## Frontend

- Add a lightweight page nav (`Dashboard` / `Draft Board` / `Playbook`),
  mirroring the artifact's own section-nav pattern, reusing the existing
  dark turf/chalk/amber theme (`frontend/styles.css`).
- **Draft Board page**: search box, position filter tabs, target/watch
  toggles, hide-drafted toggle, tier-grouped player list, click-to-mark
  interaction, recommendation panel with position bars, reset button — ported
  close to 1:1 from the artifact, with `window.storage` calls replaced by
  fetches to `/api/players` and `/api/players/draft-state`.
- **Dashboard page**: two new cards — "Roster Risk Flags" and "Free Agent
  Target Matches" — populated from the two new analysis endpoints, following
  the existing card/`emptyState()` pattern already used for roster/matchups/
  standings/transactions.
- **Playbook page**: static render of `PLAYBOOK_RULES` as rule cards, ported
  from the artifact's markup.

## Error Handling

Consistent with the existing Phase 1 convention (clear empty states, never a
crash):

- `roster-flags` / `free-agent-matches` return an empty result with a
  friendly note when the underlying sync data doesn't exist yet, rather than
  a 404 — these are "analysis views," not "give me raw data."
- Pre-draft (today), roster and free-agents will be empty/near-empty; the UI
  correctly shows "nothing flagged yet" rather than erroring.

## Testing

No automated test suite exists in this project (personal, single-user, "keep
it simple" per `CLAUDE.md`), and none is introduced here. Verification is
manual: load the app, exercise the Draft Board (search/filter/mark/reset),
confirm the Playbook renders, run a sync and confirm the two new analysis
cards degrade gracefully pre-draft.
