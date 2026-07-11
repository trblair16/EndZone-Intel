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


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
