"""Draft recommendation engine and roster/free-agent cross-referencing.

Pure functions only - no ESPN or FastAPI imports, so this stays testable
and reusable independent of how the data got here.
"""

LEAGUE_SIZE = 10  # official as of 2026-07 - update if the league grows back to 12
POSITION_TARGETS = {
    "RB": {"min": 5, "max": 6, "earliest": 1, "label": "RB"},
    "WR": {"min": 5, "max": 6, "earliest": 1, "label": "WR"},
    "QB": {"min": 2, "max": 2, "earliest": 7, "label": "QB"},
    "TE": {"min": 2, "max": 2, "earliest": 9, "label": "TE"},
    "DST": {"min": 1, "max": 1, "earliest": 14, "label": "D/ST"},
    "K": {"min": 1, "max": 1, "earliest": 15, "label": "K"},
}


def compute_recommendation(players: list, draft_state: dict) -> dict:
    my_players = [p for p in players if draft_state.get(p["name"]) == "mine"]
    total_picks = sum(1 for v in draft_state.values() if v in ("mine", "gone"))
    round_ = min(16, total_picks // LEAGUE_SIZE + 1)

    counts = {"RB": 0, "WR": 0, "QB": 0, "TE": 0, "DST": 0, "K": 0}
    for p in my_players:
        if p["pos"] in counts:
            counts[p["pos"]] += 1

    scored = []
    for pos, t in POSITION_TARGETS.items():
        count = counts[pos]
        need = max(0, t["min"] - count)
        if round_ < t["earliest"]:
            gap = t["earliest"] - round_
            weight = max(0.05, 1 - gap * 0.18) if need > 0 else 0
        else:
            overdue = round_ - t["earliest"]
            weight = 1 + overdue * 0.15
        bias = 0.05 if pos == "RB" else 0
        scored.append({
            "pos": pos, "count": count, "min": t["min"], "max": t["max"],
            "label": t["label"], "score": need * weight + bias,
            "need": need, "full": count >= t["max"],
        })

    scored.sort(key=lambda s: s["score"], reverse=True)
    return {"round": round_, "counts": counts, "scored": scored}


def cycle_draft_state(draft_state: dict, name: str) -> dict:
    current = draft_state.get(name)
    next_state = {None: "mine", "mine": "gone", "gone": None}[current]
    updated = dict(draft_state)
    if next_state is None:
        updated.pop(name, None)
    else:
        updated[name] = next_state
    return updated


def roster_risk_flags(roster: dict, players: list) -> list:
    by_name = {p["name"]: p for p in players}
    flagged = []
    for rostered in roster.get("players", []):
        match = by_name.get(rostered["name"])
        if match and match["flags"]:
            flagged.append({"name": match["name"], "pos": match["pos"], "flags": match["flags"]})
    return flagged


def free_agent_matches(free_agents: list, players: list) -> list:
    by_name = {p["name"]: p for p in players if p["target"] or p["watch"]}
    matches = []
    for fa in free_agents:
        match = by_name.get(fa["name"])
        if match:
            matches.append({
                "name": match["name"], "pos": match["pos"], "team": match["team"],
                "tier": match["tier"], "target": match["target"], "watch": match["watch"],
            })
    return matches


def reconcile_live_picks(draft_state: dict, live_picks: list, players: list, my_team_id) -> dict:
    known_names = {p["name"] for p in players}
    updated = dict(draft_state)
    for pick in live_picks:
        name = pick["player_name"]
        if name not in known_names:
            continue
        updated[name] = "mine" if pick["team_id"] == my_team_id else "gone"
    return updated
