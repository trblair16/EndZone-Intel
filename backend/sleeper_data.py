"""Free, no-auth NFL player market data from Sleeper's public API.

This is NOT a league data source - see espn_client.LeagueProvider for
that. Sleeper's API needs no login, no league connection, and no
subscription; it pulls a large-sample, currently-updated market signal
(their own internal player popularity rank, plus platform-wide
add/drop trends) as a free stand-in for a paid expert-consensus feed
like FantasyPros. It's informational only - merged into the Draft
Board/Simulator as a third comparison point alongside hand rank and
ESPN's live rank, never fed into `analysis._expected_pick`'s automatic
pick-order logic.

Caveat: this was written from documented Sleeper API knowledge, not a
live test - the sandboxed environment this was built in has no general
internet egress (confirmed by testing; only a fixed domain allowlist is
reachable), so the actual response shape has not been verified end to
end. Click "Refresh Sleeper Data" once on your own machine and confirm
`GET /api/sleeper/status` shows a real player count before trusting this
on draft day. Every function here degrades to an empty result on any
failure rather than crashing, but "quietly returning nothing" is still
worth confirming isn't what's happening.

Sleeper's own docs ask that the full player list not be pulled more than
once a day (it rarely changes and is multi-megabytes), so this is wired
to a manual refresh endpoint, not the main ESPN /api/sync loop.
"""
import requests

PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
TRENDING_ADD_URL = "https://api.sleeper.app/v1/players/nfl/trending/add"

REQUEST_TIMEOUT = 20


def get_sleeper_market_data() -> dict:
    """Returns {full_name: {"search_rank": int, "trending_add_count": int}}
    (either key may be absent per player). search_rank is Sleeper's own
    rough overall popularity/ranking metric across their whole platform -
    not a curated expert ranking, but free, live, and large-sample.
    """
    try:
        resp = requests.get(PLAYERS_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        players_by_id = resp.json()
    except Exception:
        return {}

    if not isinstance(players_by_id, dict):
        return {}

    id_to_name = {}
    market = {}
    for player_id, entry in players_by_id.items():
        if not isinstance(entry, dict):
            continue
        name = entry.get("full_name")
        if not name:
            continue
        id_to_name[player_id] = name
        rank = entry.get("search_rank")
        if rank is not None:
            market[name] = {"search_rank": rank}

    try:
        trending = requests.get(
            TRENDING_ADD_URL,
            params={"lookback_hours": 24, "limit": 100},
            timeout=15,
        )
        trending.raise_for_status()
        for entry in trending.json():
            name = id_to_name.get(entry.get("player_id"))
            count = entry.get("count")
            if name and count is not None:
                market.setdefault(name, {})["trending_add_count"] = count
    except Exception:
        pass  # trending is a bonus signal - ranks alone are still useful

    return market
