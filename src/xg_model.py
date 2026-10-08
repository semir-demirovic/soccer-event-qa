"""Train a simple expected-goals (xG) model and compare it with StatsBomb's xG."""
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

DSN = os.environ.get("DATABASE_URL", "dbname=soccer")
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

# StatsBomb pitch: 120 x 80, goal centred at (120, 40), posts at y = 36 and y = 44.
GOAL_X, GOAL_Y, HALF_GOAL_WIDTH = 120.0, 40.0, 4.0

SHOTS_SQL = """
SELECT e.match_id, l.player_name, e.x, e.y, e.shot_xg AS sb_xg,
       e.shot_outcome = 'Goal'                                   AS goal,
       e.shot_body_part = 'Head'                                 AS header,
       e.shot_type = 'Free Kick'                                 AS free_kick,
       coalesce((e.raw -> 'shot' ->> 'first_time')::boolean, false) AS first_time,
       e.under_pressure,
       e.play_pattern = 'From Counter'                           AS counter
FROM events e
JOIN lineups l USING (match_id, player_id)
WHERE e.type = 'Shot' AND e.period < 5 AND e.shot_type <> 'Penalty'
"""

FEATURES = ["distance", "angle", "header", "free_kick", "first_time", "under_pressure", "counter"]


def load_shots() -> pd.DataFrame:
    with psycopg.connect(DSN) as conn:
        cur = conn.execute(SHOTS_SQL)
        df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    for col in ("x", "y", "sb_xg"):
        df[col] = df[col].astype(float)
    return df


def add_geometry(df: pd.DataFrame) -> pd.DataFrame:
    dx = GOAL_X - df["x"]
    dy = df["y"] - GOAL_Y
    df["distance"] = np.hypot(dx, dy)
    # Angle between the two posts as seen from the shot location (radians).
    df["angle"] = np.arctan2(2 * HALF_GOAL_WIDTH * dx, dx**2 + dy**2 - HALF_GOAL_WIDTH**2)
    return df


def evaluate(name: str, y, p) -> None:
    print(f"{name:<13} log loss {log_loss(y, p):.4f} | Brier {brier_score_loss(y, p):.4f} | "
          f"AUC {roc_auc_score(y, p):.3f} | total xG {p.sum():.1f}")


def calibration_plot(df: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 6))
    for col, label in (("our_xg", "Our model"), ("sb_xg", "StatsBomb xG")):
        bins = pd.qcut(df[col], 10, duplicates="drop")
        grouped = df.groupby(bins, observed=True).agg(pred=(col, "mean"), actual=("goal", "mean"))
        ax.plot(grouped["pred"], grouped["actual"], marker="o", label=label)
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", label="Perfect calibration")
    ax.set_xlim(0, 0.8)
    ax.set_ylim(0, 0.8)
    ax.set_xlabel("Predicted goal probability (decile average)")
    ax.set_ylabel("Actual goal rate")
    ax.set_title("xG calibration - World Cup 2022, non-penalty shots")
    ax.legend()
    fig.tight_layout()
    path.parent.mkdir(exist_ok=True)
    fig.savefig(path, dpi=150)


def main():
    df = add_geometry(load_shots())
    X = df[FEATURES].astype(float)
    y = df["goal"].astype(int)

    model = make_pipeline(StandardScaler(), LogisticRegression())
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    # Out-of-fold predictions: every shot is scored by a model that never saw it.
    df["our_xg"] = cross_val_predict(model, X, y, cv=cv, method="predict_proba")[:, 1]

    print(f"{len(df)} non-penalty shots, {y.sum()} goals\n")
    evaluate("Our model", y, df["our_xg"])
    evaluate("StatsBomb xG", y, df["sb_xg"])

    model.fit(X, y)
    coefs = pd.Series(model[-1].coef_[0], index=FEATURES).sort_values()
    print("\nStandardized coefficients (negative = lowers goal probability):")
    print(coefs.round(3).to_string())

    players = (df.groupby("player_name")
                 .agg(shots=("goal", "size"), goals=("goal", "sum"),
                      our_xg=("our_xg", "sum"), sb_xg=("sb_xg", "sum"))
                 .assign(goals_minus_sb_xg=lambda t: t["goals"] - t["sb_xg"]))
    print("\nTop non-penalty finishers (goals minus StatsBomb xG, min. 5 shots):")
    print(players[players["shots"] >= 5]
          .sort_values("goals_minus_sb_xg", ascending=False).head(8).round(2).to_string())

    calibration_plot(df, DOCS_DIR / "xg_calibration.png")
    print(f"\nCalibration plot saved to {DOCS_DIR / 'xg_calibration.png'}")


if __name__ == "__main__":
    main()
