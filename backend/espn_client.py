"""ESPN Fantasy data access, normalized behind a provider-agnostic interface.

`LeagueProvider` is the contract every downstream feature (Phase 2 tier
board, Phase 3 start/sit logic, etc.) should code against. `ESPNProvider`
is the only thing here that knows about espn-api's raw object shapes -
adding Yahoo/Sleeper later means writing a new provider class, not
touching anything that consumes this interface.
"""
from abc import ABC, abstractmethod
from typing import Optional

from . import league_settings


class LeagueProvider(ABC):
    @abstractmethod
    def get_roster(self, team_id: Optional[int] = None) -> dict:
        ...

    @abstractmethod
    def get_standings(self) -> list:
        ...

    @abstractmethod
    def get_matchups(self, week: Optional[int] = None) -> list:
        ...

    @abstractmethod
    def get_transactions(self, size: int = 25) -> list:
        ...

    @abstractmethod
    def get_free_agents(self, size: int = 50, position: Optional[str] = None) -> list:
        ...

    @abstractmethod
    def get_live_picks(self) -> list:
        ...

    @abstractmethod
    def get_player_news(self, player_id: int, size: int = 5) -> list:
        ...


class ESPNProvider(LeagueProvider):
    def __init__(self, league_id: int, year: int, espn_s2: Optional[str] = None, swid: Optional[str] = None):
        from espn_api.football import League

        self._league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)

    def _team_by_id(self, team_id: int):
        for team in self._league.teams:
            if team.team_id == team_id:
                return team
        return None

    @staticmethod
    def _serialize_team(team) -> dict:
        return {
            "team_id": team.team_id,
            "team_name": team.team_name,
            "wins": team.wins,
            "losses": team.losses,
            "ties": team.ties,
            "points_for": team.points_for,
            "points_against": team.points_against,
        }

    @staticmethod
    def _serialize_player(player) -> dict:
        return {
            "player_id": player.playerId,
            "name": player.name,
            "position": player.position,
            "pro_team": player.proTeam,
            "injury_status": player.injuryStatus,
            "lineup_slot": player.lineupSlot,
            "total_points": player.total_points,
            "projected_total_points": player.projected_total_points,
        }

    def get_roster(self, team_id: Optional[int] = None) -> dict:
        team = self._team_by_id(team_id) if team_id is not None else self._league.teams[0]
        if team is None:
            raise ValueError(f"No team found with id {team_id}")
        data = self._serialize_team(team)
        data["players"] = [self._serialize_player(p) for p in team.roster]
        return data

    def get_standings(self) -> list:
        return [
            {"rank": i + 1, **self._serialize_team(team)}
            for i, team in enumerate(self._league.standings())
        ]

    def get_matchups(self, week: Optional[int] = None) -> list:
        week = week or self._league.current_week
        try:
            box_scores = self._league.box_scores(week)
        except KeyError:
            # espn-api expects a roster-for-scoring-period entry per team, which
            # doesn't exist until the league has drafted. Pre-draft, "no
            # matchups yet" is correct, not an error.
            return []

        matchups = []
        for box in box_scores:
            matchups.append(
                {
                    "week": week,
                    "home_team": box.home_team.team_name if box.home_team else "BYE",
                    "home_score": box.home_score,
                    "away_team": box.away_team.team_name if box.away_team else "BYE",
                    "away_score": box.away_score,
                    "is_playoff": box.is_playoff,
                }
            )
        return matchups

    def get_transactions(self, size: int = 25) -> list:
        transactions = []
        for activity in self._league.recent_activity(size=size):
            for team, action, player, bid in activity.actions:
                transactions.append(
                    {
                        "date": activity.date,
                        "team": team.team_name if team else None,
                        "action": action,
                        "player": player.name if hasattr(player, "name") else str(player),
                        "bid_amount": bid,
                    }
                )
        return transactions

    def get_free_agents(self, size: int = 50, position: Optional[str] = None) -> list:
        return [self._serialize_player(p) for p in self._league.free_agents(size=size, position=position)]

    def get_live_picks(self) -> list:
        self._league.refresh_draft(refresh_players=True)
        return [
            {
                "team_id": pick.team.team_id if pick.team else None,
                "player_name": pick.playerName,
            }
            for pick in self._league.draft
        ]

    def get_player_news(self, player_id: int, size: int = 5) -> list:
        try:
            data = self._league.espn_request.get_player_news(playerId=player_id)
        except Exception:
            return []
        feed = data.get("news", {}).get("feed", [])
        return [
            {
                "headline": item.get("headline"),
                "description": item.get("description"),
                "published": item.get("published"),
            }
            for item in feed[:size]
        ]


def build_provider() -> ESPNProvider:
    """Constructs a provider from the active league config (a runtime-set
    override, if any, otherwise .env), or raises RuntimeError with a
    friendly message."""
    active = league_settings.get_active()
    if not active["league_id"]:
        raise RuntimeError(
            "ESPN league not configured yet. Add LEAGUE_ID (and ESPN_S2/SWID for "
            "private leagues) to .env, or set it via League Settings, then try again."
        )
    return ESPNProvider(
        league_id=int(active["league_id"]),
        year=int(active["year"]),
        espn_s2=active["espn_s2"],
        swid=active["swid"],
    )
