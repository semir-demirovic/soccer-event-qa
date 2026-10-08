"""Download StatsBomb open data (one competition/season) into data/raw/."""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://raw.githubusercontent.com/hudl/open-data/master/data"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

session = requests.Session()


def fetch(path: str) -> bytes:
    url = f"{BASE_URL}/{path}"
    for attempt in range(3):
        resp = session.get(url, timeout=60)
        if resp.status_code == 200:
            return resp.content
        if resp.status_code == 404:
            raise FileNotFoundError(url)
        time.sleep(2 * (attempt + 1))
    resp.raise_for_status()


def save(path: str) -> Path:
    """Download a file once; skip if it already exists locally."""
    target = RAW_DIR / path
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(fetch(path))
    return target


def find_competition(competition: str, season: str) -> tuple[int, int]:
    comps = json.loads(save("competitions.json").read_text(encoding="utf-8"))
    for c in comps:
        if c["competition_name"] == competition and c["season_name"] == season:
            return c["competition_id"], c["season_id"]
    available = sorted({f'{c["competition_name"]} | {c["season_name"]}' for c in comps})
    sys.exit(f"Not found: {competition} {season}\nAvailable:\n  " + "\n  ".join(available))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition", default="FIFA World Cup")
    parser.add_argument("--season", default="2022")
    args = parser.parse_args()

    comp_id, season_id = find_competition(args.competition, args.season)
    print(f"{args.competition} {args.season}: competition_id={comp_id}, season_id={season_id}")

    matches = json.loads(save(f"matches/{comp_id}/{season_id}.json").read_text(encoding="utf-8"))
    print(f"{len(matches)} matches")

    for i, m in enumerate(matches, 1):
        mid = m["match_id"]
        save(f"events/{mid}.json")
        save(f"lineups/{mid}.json")
        print(f"[{i}/{len(matches)}] {m['home_team']['home_team_name']} vs {m['away_team']['away_team_name']}")


if __name__ == "__main__":
    main()
