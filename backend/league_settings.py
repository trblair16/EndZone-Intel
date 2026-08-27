"""Active league config: a DB-stored override, switchable at runtime, takes
priority over .env. Lets the app point at a different ESPN league (a
one-off work league on draft day, say) without hand-editing .env and
restarting the server mid-draft.

Switching leagues clears every cache key scoped to "the currently
connected league" - otherwise the old league's roster/draft state would
bleed into the new one's views.
"""
from typing import Optional

from . import config, db

CACHE_KEY = "league_config"

LEAGUE_SCOPED_CACHE_KEYS = (
    "roster",
    "standings",
    "matchups",
    "transactions",
    "free_agents",
    "espn_rankings",
    "week1_matchups",
    "draft_state",
    "sim_slot",
    "sim_draft_state",
    "sim_pick_index",
)


def get_active() -> dict:
    override = db.get_cache(CACHE_KEY)
    d = (override or {}).get("data") or {}
    return {
        "league_id": d.get("league_id") or config.LEAGUE_ID,
        "year": d.get("year") or config.YEAR,
        "espn_s2": d.get("espn_s2") if d.get("espn_s2") not in (None, "") else config.ESPN_S2,
        "swid": d.get("swid") if d.get("swid") not in (None, "") else config.SWID,
        "team_id": d.get("team_id") if d.get("team_id") not in (None, "") else config.TEAM_ID,
        "label": d.get("label") or None,
        "is_override": bool(d),
    }


def is_configured() -> bool:
    return bool(get_active()["league_id"])


def team_id_int() -> Optional[int]:
    team_id = get_active()["team_id"]
    return int(team_id) if team_id else None


def set_active(
    league_id: str,
    year: str,
    espn_s2: Optional[str] = None,
    swid: Optional[str] = None,
    team_id: Optional[str] = None,
    label: Optional[str] = None,
) -> dict:
    db.set_cache(
        CACHE_KEY,
        {
            "league_id": str(league_id) if league_id else None,
            "year": str(year) if year else None,
            "espn_s2": espn_s2 or None,
            "swid": swid or None,
            "team_id": str(team_id) if team_id else None,
            "label": label or None,
        },
    )
    db.clear_keys(LEAGUE_SCOPED_CACHE_KEYS)
    return get_active()


def reset_to_env() -> dict:
    db.clear_keys((CACHE_KEY,) + LEAGUE_SCOPED_CACHE_KEYS)
    return get_active()
