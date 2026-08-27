"""Pulls all Phase 1 data types from a provider and writes them to the cache.

Shared by the /api/sync endpoint and the standalone refresh.py script so
there's exactly one place that knows what "a sync" means.
"""
from . import db, league_settings
from .espn_client import LeagueProvider


def run_sync(provider: LeagueProvider) -> tuple[dict, dict]:
    team_id = league_settings.team_id_int()
    jobs = (
        ("roster", lambda: provider.get_roster(team_id)),
        ("standings", lambda: provider.get_standings()),
        ("matchups", lambda: provider.get_matchups()),
        ("transactions", lambda: provider.get_transactions()),
        ("free_agents", lambda: provider.get_free_agents()),
        ("espn_rankings", lambda: provider.get_espn_rankings()),
    )

    results, errors = {}, {}
    for key, fn in jobs:
        try:
            db.set_cache(key, fn())
            results[key] = "ok"
        except Exception as exc:
            errors[key] = str(exc)
    return results, errors
