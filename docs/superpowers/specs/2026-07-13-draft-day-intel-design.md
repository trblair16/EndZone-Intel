# Draft-Day Intel Additions — Design

## Context

Four small, complementary additions to help with draft prep, all sourced
from data ESPN already gives us through the existing authenticated
connection - no external scraping or new dependencies needed:

- **Player news** - real injury/beat-reporter updates per player.
- **ESPN's own draft-rank data** - fills the ADP gap for the ~90 players
  we don't have researched consensus ADP for (see
  `docs/superpowers/specs/2026-07-08-player-analysis-design.md` and the
  2026-07-11/12/13 commits merging 4for4 ADP), and keeps improving
  automatically over time instead of needing more manual research passes.
- **Bye-week collision warnings** - flag when a roster has too many
  players sharing a bye week.
- **Weekly opponent info** - show who a player's team plays in a given
  week (defaulting to Week 1), directly relevant to picking a D/ST last
  when all you otherwise see is ADP and projected points.

All four follow the architecture already established by every prior
feature in this app: `ESPNProvider` gains new methods, the sync/cache
pipeline gains new keys, and the frontend merges live data with the
static `PLAYERS` dataset at render time. `players.py` is never mutated
automatically - it stays hand-curated, matching the existing convention.

## Goals

- Surface real player news for roster/free-agent players, fetched on
  demand (not bulk-synced - fetching individual news for 50+ players on
  every sync would be slow and wasteful for data that rarely changes
  minute-to-minute).
- Backfill missing ADP-like data automatically via ESPN's own internal
  PPR rank (`draftRanksByRankType`), refreshed on every sync, used only
  as a fallback where we don't have real researched ADP.
- Warn about bye-week clustering on both the real roster (Dashboard) and
  the simulated roster (Draft Simulator).
- Show each player's Week 1 opponent (parameterized by week for future
  reuse) on the Draft Board, Free Agent Matches card, and Simulator.

## Non-Goals

- Matchup *quality* scoring (e.g. "weak run defense") - explicitly out of
  scope per direct instruction; this only shows the opponent, the user
  judges favorability themselves.
- Automatically overwriting `players.py`'s hand-curated fields - ESPN's
  live rank data lives in the cache layer, merged at read time, never
  baked into the static file.
- Full news article rendering - headline + short description/story
  snippet is enough, no need to build an article reader.
- News for hand-curated-only Draft Board players (the 147+ players not
  currently on a roster or in the free-agent pool) - would require
  fragile name-to-ESPN-ID matching with no real payoff, since news is
  most useful for players you're actively managing, not the whole board.

## A. Player News

### `backend/espn_client.py`

- Add `playerId` to `_serialize_player()`'s output (already available on
  the underlying `espn_api` `Player` object as `.playerId` - just wasn't
  being passed through).
- New method on `LeagueProvider`/`ESPNProvider`:
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

### `backend/main.py`

- `GET /api/players/{player_id}/news` - calls `provider.get_player_news`,
  returns `{"news": [...]}`. Empty list (not an error) if ESPN returns
  nothing.

### Frontend

- Roster card and Free Agent Matches card gain a small "News" link/button
  per player (only shown since these are the only two sources with a real
  `playerId`). Clicking it lazily fetches and expands the news list inline
  - no pre-fetching, no bulk loading.

## B. ESPN's Own Draft-Rank Fallback

### `backend/espn_client.py`

New method pulling ESPN's own PPR rank for the full rosterable player
pool in one request (same raw-request pattern already proven to work):

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

### `backend/sync.py`

Add `"espn_rankings"` as a sync job, same pattern as the existing four.

**Unverified assumption:** only `size=5` was tested live during design
(confirming the response shape). A single request for `size=300` may hit
a response-size limit or get truncated by ESPN - this needs to be
verified during implementation, with a pagination fallback (using the
existing `offset` filter field, same as `get_free_agents`) if a single
large request doesn't work cleanly.

### `backend/analysis.py`

`_expected_pick` gains a third priority tier. Since it's a pure function
today with no access to the cache, it needs the ESPN rankings dict passed
in explicitly:

```python
def _expected_pick(player: dict, espn_rankings: dict = None) -> int:
    if "adp_pick_overall" in player:
        return player["adp_pick_overall"]
    if player["name"] in _EXPECTED_PICK_OVERRIDES:
        return _EXPECTED_PICK_OVERRIDES[player["name"]]
    if espn_rankings and player["name"] in espn_rankings:
        return espn_rankings[player["name"]]
    return player["rank"]
```

`simulate_board_at_pick` gains an `espn_rankings: dict = None` parameter,
threaded through to both call sites of `_expected_pick` inside it. The
`/api/simulator/*` endpoints in `main.py` read the cached `espn_rankings`
entry and pass it through.

## C. Bye-Week Collision Warnings

### `backend/players.py` (or a new small `backend/bye_weeks.py`)

A static `BYE_WEEKS: dict[str, int]` (team abbreviation -> bye week number
for the 2026 season). **This needs to be researched before implementation**
- 2026 NFL schedules release after this app's knowledge cutoff, so this
  table must come from a live web search during the build, and should be
  spot-checked by the user afterward rather than trusted blindly.

### `backend/analysis.py`

```python
def bye_week_collisions(roster_players: list, bye_weeks: dict, threshold: int = 3) -> list:
    """roster_players: list of {'name', 'pro_team'} dicts (works for both
    the real roster and a simulated one). Returns [{'week': int, 'players': [...]}]
    for any week with >= threshold players on bye."""
```

### `backend/main.py`

- Dashboard: existing `GET /api/roster` response is joined with
  `bye_week_collisions` server-side, or a small new endpoint
  `GET /api/analysis/bye-weeks` mirroring the existing roster-flags/
  free-agent-matches pattern.
- Simulator: `_simulator_state_payload()` gains a `bye_warnings` key
  computed from the current `roster` list.

### Frontend

- Dashboard roster card gains a warning line beneath the roster table when
  triggered.
- Simulator's roster strip gains the same warning line.

## D. Weekly Opponent Info

### `backend/espn_client.py`

```python
def get_weekly_matchups(self, week: int = 1) -> dict:
    """Returns {team_abbr: opponent_abbr} for every NFL team in the given week."""
    schedule = self._league._get_pro_schedule(week)
    return {
        PRO_TEAM_MAP[team_id]: PRO_TEAM_MAP[opponent_id]
        for team_id, (opponent_id, _date) in schedule.items()
    }
```

(`_get_pro_schedule` is a "private" method on the underlying `espn_api`
`League` object - already the established convention in this codebase,
see `get_live_picks`'s use of `refresh_draft`/`self._league.draft`. No
public equivalent exists in the library for a standalone team-schedule
lookup without pulling full box scores.)

### `backend/sync.py`

Add `"week1_matchups"` as a sync job (calls `get_weekly_matchups(week=1)`).
Parameterized by week in the provider layer even though only Week 1 is
wired into sync today, so pulling a different week later is a one-line
change, not a redesign.

### Frontend

- Draft Board: each row's `db-meta` (currently just shows pro team) gains
  `vs. NYJ` next to the team abbreviation, looked up from the cached
  `week1_matchups` data.
- Free Agent Matches card and Simulator's available list get the same
  treatment.

## Error Handling

Consistent with every existing feature: empty/graceful results, never a
crash. `get_player_news` returns `[]` on any ESPN error. `get_espn_rankings`
degrades to an empty dict if the request fails (matches `get_matchups`'s
pre-draft `KeyError` handling precedent) - `_expected_pick` already
handles a missing/`None` rankings dict gracefully. Bye-week data with an
unrecognized team abbreviation is skipped, not a crash.

## Testing

No automated test framework (consistent with the rest of the project).
Manual verification: trigger a full sync and confirm all three new sync
jobs (`espn_rankings`, `week1_matchups`) succeed; click "News" on a
roster/free-agent player and confirm headlines render; run the Draft
Simulator through several rounds and confirm bye-week warnings and
opponent tags appear sensibly.
