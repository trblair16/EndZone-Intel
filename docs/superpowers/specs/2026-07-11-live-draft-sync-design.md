# Live Draft Auto-Sync — Design

## Context

The Draft Board (Piece A) requires manually clicking each player to cycle
them through available -> mine -> gone. During a real live draft, that means
manually marking every pick made by all 11 opponents plus your own, within a
90-second pick window, while also using ESPN's own site to actually submit
your pick. That's more divided attention than just using ESPN alone, not
less - it directly works against the reason this app exists.

`espn_api`'s `League.refresh_draft(refresh_players=True)` pulls ESPN's live
draft-detail feed (`view=mDraftDetail`), returning every pick made so far by
every team, resolved to player names via `refresh_players`. Polling this
during the live draft and auto-reconciling it into the existing
`draft_state` cache removes the manual bookkeeping entirely - your job
during your pick window becomes look at the board, decide, then go enter
the pick on ESPN (which you have to do regardless, since this app can't
submit picks for you).

This was investigated as an alternative to pulling your personal ESPN
Watch List (which turned out to require reverse-engineering an undocumented,
account-scoped endpoint with no confirmed source for the underlying ID
list). This feature directly addresses the actual underlying concern
(attention-splitting during a live draft) that motivated that request, so
the Watch List thread is dropped in favor of this.

## Goals

- Eliminate manual click-to-mark bookkeeping for opponents' picks during a
  live draft, while keeping manual clicks available as a fallback.
- Keep ESPN's servers untouched except during an explicit, user-initiated
  "Live Draft Mode" window - no background polling outside of it.
- Never crash or interrupt the draft-day experience on a failed poll or an
  ESPN player name that doesn't match our dataset.

## Non-Goals

- Submitting picks to ESPN on your behalf - out of scope entirely, this app
  stays read-only against ESPN.
- Persisting "Live Draft Mode: on" across a page reload - resets to off,
  matching this project's simplicity-first convention. You'll have the tab
  open and focused for the whole draft anyway.
- Fuzzy-matching ESPN pick names against the player dataset - exact string
  match only, same convention as the existing roster/free-agent
  cross-referencing. Unmatched picks (late-round players not in the 147-
  player dataset, naming mismatches) are silently skipped - there's nothing
  useful to mark for a player not in the dataset anyway.
- Reverse-engineering the ESPN personal Watch List endpoint - superseded by
  this feature.

## Known Verification Limitation

`refresh_draft()` against a league that hasn't started returns an empty
pick list (mirrors the existing `get_matchups()` pre-draft behavior) - this
path is testable today. The actual live-pick-flow, however, can only be
verified against a real, in-progress league draft - ESPN's mock draft tool
runs in a separate context that does not populate this league's real
`draftDetail` feed. Manual click-to-mark must remain fully functional as a
fallback in case anything about the live sync doesn't behave as expected on
draft day.

## Architecture

**Polling is frontend-driven** (browser calls a backend endpoint on an
interval), not a backend background task. Turning "Live Draft Mode" off is
just `clearInterval` - no server-side lifecycle, no threading, no new
moving parts beyond what the rest of this codebase already has. Each poll
is independent and self-healing: if one poll fails or a manual click
temporarily disagrees with ESPN, the next poll 5 seconds later corrects it.

### `backend/espn_client.py`

New abstract method on `LeagueProvider` and implementation on `ESPNProvider`:

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

### `backend/analysis.py`

New pure function, following the existing non-mutating convention used by
`cycle_draft_state`:

```python
def reconcile_live_picks(draft_state: dict, live_picks: list, players: list, my_team_id: int) -> dict:
    by_name = {p["name"] for p in players}
    updated = dict(draft_state)
    for pick in live_picks:
        name = pick["player_name"]
        if name not in by_name:
            continue
        updated[name] = "mine" if pick["team_id"] == my_team_id else "gone"
    return updated
```

### `backend/main.py`

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

Reuses the existing `_players_payload()` helper and the existing
`draft_state` cache key - no new storage, no schema change.

### Frontend (`frontend/draftboard.js`, `frontend/index.html`, `frontend/styles.css`)

- A "Live Draft Mode" toggle button in the Draft Board's control bar.
- A status line next to it: `Live Draft Mode: ON — last synced Xs ago`,
  updated on each successful poll; `sync issue, retrying...` on a failed
  poll. No alert popups for poll failures - a failed poll silently retries
  on the next tick.
- On toggle-on: call `/api/draft/live-sync` immediately, then every 5
  seconds via `setInterval`. Each response updates `dbPlayers` /
  `dbRecommendation` and re-renders through the existing render functions -
  no new rendering path needed.
- On toggle-off: `clearInterval`, status line clears.
- Manual click-to-mark (`markDraftState`) remains fully functional at all
  times, on or off. If Live Draft Mode is on and ESPN later reports that
  same player picked, ESPN's value overwrites the manual one on the next
  poll.

## Error Handling

- A failed `/api/draft/live-sync` call (network blip, ESPN hiccup) is
  caught client-side, does not clear the interval, and does not alert -
  it just updates the status line to "sync issue, retrying..." and waits
  for the next 5-second tick.
- ESPN picks for players not in `PLAYERS` are silently skipped server-side -
  no error, no visible indicator, consistent with the earlier decision that
  a stressful moment shouldn't be interrupted by cosmetic warnings.
- Pre-draft (today), `get_live_picks()` returns `[]` and `live-sync` is a
  safe no-op - this is the only path verifiable outside of an actual live
  draft.

## Testing

No automated test suite, consistent with the rest of this project. Manual
verification today is limited to: toggling Live Draft Mode on with no
draft in progress and confirming it polls every 5 seconds without error,
shows the status line updating, and can be toggled off cleanly. Full
verification against real opponent picks can only happen on draft day
itself.
