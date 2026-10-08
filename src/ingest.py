"""Load raw StatsBomb JSON from data/raw/ into PostgreSQL."""
import json
import os
import uuid
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DSN = os.environ.get("DATABASE_URL", "dbname=soccer")

MATCH_SQL = """
INSERT INTO matches (match_id, competition_id, season_id, match_date, stage,
                     home_team_id, home_team, away_team_id, away_team, home_score, away_score)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (match_id) DO UPDATE SET
    home_score = EXCLUDED.home_score, away_score = EXCLUDED.away_score, stage = EXCLUDED.stage
"""

LINEUP_SQL = """
INSERT INTO lineups (match_id, team_id, player_id, player_name, jersey)
VALUES (%s, %s, %s, %s, %s)
"""

EVENT_COLS = [
    "id", "match_id", "idx", "period", "ts", "minute", "second", "type",
    "possession", "possession_team_id", "play_pattern", "team_id", "player_id", "position",
    "x", "y", "end_x", "end_y", "under_pressure", "related_events",
    "pass_recipient_id", "pass_outcome", "shot_outcome", "shot_xg", "shot_body_part", "shot_type",
    "card", "raw",
]
EVENT_SQL = f"INSERT INTO events ({', '.join(EVENT_COLS)}) VALUES ({', '.join(['%s'] * len(EVENT_COLS))})"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def xy(loc):
    return (loc[0], loc[1]) if loc else (None, None)


def end_location(e):
    for key in ("pass", "carry", "shot"):
        if key in e and "end_location" in e[key]:
            return e[key]["end_location"]
    return None


def match_row(m):
    return (
        m["match_id"], m["competition"]["competition_id"], m["season"]["season_id"],
        m["match_date"], m.get("competition_stage", {}).get("name"),
        m["home_team"]["home_team_id"], m["home_team"]["home_team_name"],
        m["away_team"]["away_team_id"], m["away_team"]["away_team_name"],
        m["home_score"], m["away_score"],
    )


def event_row(match_id, e):
    x, y = xy(e.get("location"))
    end_x, end_y = xy(end_location(e))
    pas = e.get("pass", {})
    shot = e.get("shot", {})
    card = (e.get("foul_committed", {}).get("card")
            or e.get("bad_behaviour", {}).get("card") or {}).get("name")
    return (
        uuid.UUID(e["id"]), match_id, e["index"], e["period"], e["timestamp"],
        e["minute"], e["second"], e["type"]["name"],
        e.get("possession"), e.get("possession_team", {}).get("id"),
        e.get("play_pattern", {}).get("name"),
        e.get("team", {}).get("id"), e.get("player", {}).get("id"),
        e.get("position", {}).get("name"),
        x, y, end_x, end_y,
        e.get("under_pressure", False),
        [uuid.UUID(r) for r in e.get("related_events", [])],
        pas.get("recipient", {}).get("id"), pas.get("outcome", {}).get("name"),
        shot.get("outcome", {}).get("name"), shot.get("statsbomb_xg"),
        shot.get("body_part", {}).get("name"), shot.get("type", {}).get("name"),
        card, Jsonb(e),
    )


def lineup_rows(match_id, teams):
    for t in teams:
        for p in t["lineup"]:
            yield match_id, t["team_id"], p["player_id"], p["player_name"], p.get("jersey_number")


def main():
    match_files = sorted(RAW_DIR.glob("matches/*/*.json"))
    with psycopg.connect(DSN, autocommit=True) as conn:
        for mf in match_files:
            for m in load(mf):
                mid = m["match_id"]
                ev_path = RAW_DIR / "events" / f"{mid}.json"
                lu_path = RAW_DIR / "lineups" / f"{mid}.json"
                if not ev_path.exists():
                    continue
                events = load(ev_path)
                with conn.transaction(), conn.cursor() as cur:
                    cur.execute(MATCH_SQL, match_row(m))
                    cur.execute("DELETE FROM events WHERE match_id = %s", (mid,))
                    cur.execute("DELETE FROM lineups WHERE match_id = %s", (mid,))
                    cur.executemany(EVENT_SQL, [event_row(mid, e) for e in events])
                    cur.executemany(LINEUP_SQL, list(lineup_rows(mid, load(lu_path))))
                print(f"{mid}: {m['home_team']['home_team_name']} vs "
                      f"{m['away_team']['away_team_name']} - {len(events)} events")


if __name__ == "__main__":
    main()
