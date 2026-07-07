from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import config, db
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


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
