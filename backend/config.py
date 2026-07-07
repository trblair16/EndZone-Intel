"""Loads league config from .env. Left blank until the user provides credentials."""
import os

from dotenv import load_dotenv

load_dotenv()

LEAGUE_ID = os.getenv("LEAGUE_ID") or None
YEAR = os.getenv("YEAR", "2026")
ESPN_S2 = os.getenv("ESPN_S2") or None
SWID = os.getenv("SWID") or None
TEAM_ID = os.getenv("TEAM_ID") or None


def is_configured() -> bool:
    return bool(LEAGUE_ID)


def team_id_int():
    return int(TEAM_ID) if TEAM_ID else None
