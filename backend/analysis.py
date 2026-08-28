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
    # Hand-curated flags in players.py are a June/July snapshot - a real
    # roster player's own live injury_status (already pulled fresh from
    # ESPN on every sync, see ESPNProvider._serialize_player) can surface
    # an injury here even for a player with no hand-set flag at all, or
    # one who isn't in the hand-curated board's 169 players in the first
    # place.
    by_name = {p["name"]: p for p in players}
    flagged = []
    for rostered in roster.get("players", []):
        match = by_name.get(rostered["name"])
        flags = list(match["flags"]) if match and match["flags"] else []
        live_status = rostered.get("injury_status")
        if live_status and live_status != "ACTIVE" and "injury" not in flags:
            flags.append("injury")
        if flags:
            flagged.append({
                "name": rostered["name"],
                "pos": match["pos"] if match else rostered.get("position"),
                "flags": flags,
                "live_injury_status": live_status if live_status != "ACTIVE" else None,
            })
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


def bye_week_collisions(roster_players: list, bye_weeks: dict, threshold: int = 3) -> list:
    """roster_players: list of {'name', 'pro_team'} dicts (works for both
    the real roster and a simulated one). Returns [{'week': int, 'players': [...]}]
    for any week with >= threshold players on bye."""
    by_week = {}
    for p in roster_players:
        team = p.get("pro_team") or p.get("team")
        week = bye_weeks.get(team)
        if week is None:
            continue
        by_week.setdefault(week, []).append(p["name"])

    return [
        {"week": week, "players": names}
        for week, names in sorted(by_week.items())
        if len(names) >= threshold
    ]


def snake_pick_numbers(slot: int, rounds: int = 16, league_size: int = LEAGUE_SIZE) -> list:
    picks = []
    for round_ in range(1, rounds + 1):
        pick_in_round = slot if round_ % 2 == 1 else league_size - slot + 1
        picks.append((round_ - 1) * league_size + pick_in_round)
    return picks


# The rank-collision fix in players.py ("Dedupe rank values" commit)
# renumbered a handful of players far outside their tier's normal range to
# get unique ranks - fine for its own purpose (breaking display ties within
# a tier), but it corrupts these specific players' use as a fallback
# "expected pick" for simulator depletion, since their rank no longer
# resembles real draft timing at all (e.g. Drake Maye is tier 3, alongside
# QBs ranked in the low 30s, but his rank was pushed to 95). These are
# rough tier-consistent estimates, not researched ADP - just enough to stop
# these specific players from lingering in the simulator's "available" pool
# many rounds past where they plausibly belong.
_EXPECTED_PICK_OVERRIDES = {
    "Drake Maye": 36,
    "Jalen Hurts": 40,
    "Bhayshul Tuten": 60,
    "Caleb Williams": 61,
    "Matthew Stafford": 63,
    "Tyler Shough": 93,
    "Stefon Diggs": 115,
    # Colston Loveland, Kyle Pitts Sr., and Tyler Warren were researched and
    # given real adp_pick_overall values in players.py - removed here since
    # _expected_pick() checks adp_pick_overall first anyway.
}


def _expected_pick(player: dict, espn_rankings: dict = None) -> int:
    # ESPN's own live-synced PPR rank (refreshed on every sync) now takes
    # priority over the frozen July 2026 4for4 ADP pull baked into
    # players.py's adp_pick_overall field - a live feed is more current
    # than a two-month-old snapshot taken before preseason even wrapped.
    # The frozen ADP is kept as a fallback for anyone ESPN's rank pull
    # doesn't cover, then the handful of known-bad rank overrides, then
    # finally the raw hand-curated rank as a last resort.
    espn_entry = (espn_rankings or {}).get(player["name"])
    if espn_entry and "rank" in espn_entry:
        return espn_entry["rank"]
    if "adp_pick_overall" in player:
        return player["adp_pick_overall"]
    if player["name"] in _EXPECTED_PICK_OVERRIDES:
        return _EXPECTED_PICK_OVERRIDES[player["name"]]
    return player["rank"]


def simulate_board_at_pick(players: list, sim_state: dict, overall_pick: int, espn_rankings: dict = None) -> dict:
    effective_state = dict(sim_state)
    for p in players:
        name = p["name"]
        if name in effective_state:
            continue
        if _expected_pick(p, espn_rankings) <= overall_pick - 1:
            effective_state[name] = "gone"

    recommendation = compute_recommendation(players, effective_state)

    available = [
        p for p in players
        if effective_state.get(p["name"]) not in ("mine", "gone")
    ]
    available.sort(key=lambda p: _expected_pick(p, espn_rankings))

    return {
        "round": recommendation["round"],
        "counts": recommendation["counts"],
        "scored": recommendation["scored"],
        "available": available[:10],
    }
