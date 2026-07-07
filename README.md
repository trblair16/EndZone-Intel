# EndZone-Intel
A local, personal fantasy football dashboard that pulls live ESPN league data and layers in custom draft rankings, risk flags, and decision rules.

## Phase 1: read-only ESPN mirror

Runs entirely on `localhost` — no hosting, no Docker, no real database.

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in LEAGUE_ID / ESPN_S2 / SWID / TEAM_ID
```

### Run

```bash
uvicorn backend.main:app --reload
```

Open `http://localhost:8000`. The dashboard loads fine with `.env` empty — it just
shows "not configured" until you add your league's `LEAGUE_ID` (and `ESPN_S2`/`SWID`
cookies for a private league), then click **Sync Now**.

You can also refresh the cache from the command line any time:

```bash
python refresh.py
```
