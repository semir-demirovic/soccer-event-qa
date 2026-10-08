# Soccer Event Data QA & Analytics

Data quality validation and analytics on **StatsBomb open event data** for the **FIFA World Cup 2022**:
64 matches, 234,637 events, built with **Python** and **PostgreSQL**.

## Why

Every advanced metric (xG, possession value, pressing intensity, player ratings) is computed from event data.
A wrong timestamp, a missing goal or a pass credited to the wrong team silently corrupts everything downstream.
This project builds an ingestion pipeline plus a set of SQL checks that act as **regression tests for every new batch of matches**.

## Pipeline

    StatsBomb JSON  ->  src/download.py     ->  data/raw/
                    ->  src/ingest.py       ->  PostgreSQL: matches, lineups, events
                    ->  sql/validation.sql  ->  qa.* views + qa.summary

Design choices:

- **Normalized columns + raw `jsonb`.** Key fields (type, player, location, xG, outcomes) are typed columns for fast queries;
  the full original event is kept in `raw`, so nothing is lost and every value can be audited against the source.
- **Idempotent loading.** Each match is loaded in its own transaction (delete + insert), so the pipeline can be re-run safely.
- **Checks return failing rows.** Each `qa.*` view lists only the rows that fail; an empty view means the check passed.

## Quick start

    pip install -r requirements.txt
    python src/download.py                  # default: FIFA World Cup 2022
    createdb soccer
    psql -d soccer -f sql/schema.sql
    python src/ingest.py
    psql -d soccer -f sql/validation.sql
    psql -d soccer -c "SELECT * FROM qa.summary;"

## Validation checks

| # | Check | Rule | Result |
|---|---|---|---|
| 1 | `goal_mismatch` | Goals in the event stream equal the official score (own goals included, penalty shootout excluded) | ✅ 0 |
| 2 | `events_after_red_card` | A sent-off player has no later on-pitch events | ✅ 0 |
| 3 | `events_outside_sub_window` | No events before a substitute comes on or after a replaced player goes off | ✅ 0 |
| 4 | `bad_pass_recipient` | A pass recipient belongs to the passer's team | ✅ 0 |
| 5 | `location_out_of_bounds` | All coordinates are on the 120 x 80 pitch | ✅ 0 |
| 6 | `broken_related_events` | Every related event exists and belongs to the same match | ✅ 0 |
| 7 | `time_goes_backwards` | Event time never jumps backwards by more than 1 second within a period | ⚠️ 2 |
| 8 | `incomplete_shots` | Every shot has xG, location and outcome | ✅ 0 |

The 1-second tolerance in check 7 is deliberate: sub-second ordering noise between simultaneous events is normal,
and a zero-tolerance rule would bury real problems in false alarms.

## Finding: reset timestamps in the World Cup final

Check 7 flagged two events, both in **Argentina vs France** (match `3869685`):

| Event | Linked pass | Recorded time | Expected time |
|---|---|---|---|
| Ball Receipt, Camavinga (idx 3438) | Tchouaméni, **98:35** (idx 3437) | **45:00** (`00:00:00.275`) | 98:35.9 – 98:37.9 |
| Ball Receipt, Camavinga (idx 3975) | Fofana, **106:02** (idx 3974) | **90:00** (`00:00:00.620`) | 106:02.5 – 106:04.6 |

Investigation:

1. **Not a pipeline bug.** The original `timestamp` in the raw JSON matches the loaded value.
2. **All time fields are affected consistently.** `timestamp`, `minute` and `second` all point to the *start* of the period.
3. **Same pattern twice.** Same event type, same player, both in the last two seconds before the period-ending whistle.
   This looks systematic (an event recorded at the whistle receiving a default time of zero) rather than random noise.
4. **Correct position confirmed.** Both receipts are linked via `related_events` to the pass immediately before them,
   so the true time is bounded by that pass and the `Half End` event.

Handling: **flag, don't silently fix.** Keep the original value, add a corrected timestamp bounded by the
neighbouring events, and record the reason. Next step would be to scan other competitions for the same
pattern and, if it recurs, report it to the provider.

## Data source

Data provided by [StatsBomb](https://github.com/hudl/open-data) (Hudl) open data, used under their terms for research purposes.
