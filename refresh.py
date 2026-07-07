"""Standalone "pull latest from ESPN" script. Run any time: python refresh.py"""
from backend import db
from backend.espn_client import build_provider
from backend.sync import run_sync


def main() -> None:
    try:
        provider = build_provider()
    except RuntimeError as exc:
        print(exc)
        return

    db.init_db()
    results, errors = run_sync(provider)
    for key in results:
        print(f"synced {key}")
    for key, message in errors.items():
        print(f"failed to sync {key}: {message}")


if __name__ == "__main__":
    main()
