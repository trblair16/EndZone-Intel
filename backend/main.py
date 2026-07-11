from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analysis, config, db
from . import players as players_data
from .espn_client import build_provider
from .sync import run_sync

app = FastAPI(title="EndZone Intel")

db.init_db()


@app.get("/api/status")
def status():
    return {
        "configured": config.is_configured(),
        "league_id": config.LEAGUE_ID,
        "year": config.YEAR,
        "team_id": config.TEAM_ID,
        "cache": db.all_cache_status(),
    }


@app.post("/api/sync")
def sync():
    try:
        provider = build_provider()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    results, errors = run_sync(provider)
    if errors and not results:
        raise HTTPException(status_code=502, detail={"message": "Sync failed", "errors": errors})
    return {"synced": results, "errors": errors}


def _cached_or_404(key: str, friendly_name: str):
    cached = db.get_cache(key)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail=f"No {friendly_name} cached yet. Configure .env and click Sync Now.",
        )
    return cached


@app.get("/api/roster")
def roster():
    return _cached_or_404("roster", "roster")


@app.get("/api/standings")
def standings():
    return _cached_or_404("standings", "standings")


@app.get("/api/matchups")
def matchups():
    return _cached_or_404("matchups", "matchups")


@app.get("/api/transactions")
def transactions():
    return _cached_or_404("transactions", "transactions")


def _players_payload():
    draft_state = (db.get_cache("draft_state") or {"data": {}})["data"]
    merged = [{**p, "state": draft_state.get(p["name"], "available")} for p in players_data.PLAYERS]
    recommendation = analysis.compute_recommendation(players_data.PLAYERS, draft_state)
    return {"players": merged, "recommendation": recommendation}


@app.get("/api/players")
def players():
    return _players_payload()


class DraftStateRequest(BaseModel):
    name: str


@app.post("/api/players/draft-state")
def set_draft_state(body: DraftStateRequest):
    current = (db.get_cache("draft_state") or {"data": {}})["data"]
    updated = analysis.cycle_draft_state(current, body.name)
    db.set_cache("draft_state", updated)
    return _players_payload()


@app.post("/api/players/reset-draft-state")
def reset_draft_state():
    db.set_cache("draft_state", {})
    return _players_payload()


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


@app.get("/api/playbook")
def playbook():
    return {"rules": players_data.PLAYBOOK_RULES}


@app.get("/api/analysis/roster-flags")
def roster_flags():
    cached = db.get_cache("roster")
    if cached is None:
        return {"data": []}
    return {"data": analysis.roster_risk_flags(cached["data"], players_data.PLAYERS)}


@app.get("/api/analysis/free-agent-matches")
def free_agent_matches_endpoint():
    cached = db.get_cache("free_agents")
    if cached is None:
        return {"data": []}
    return {"data": analysis.free_agent_matches(cached["data"], players_data.PLAYERS)}


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
