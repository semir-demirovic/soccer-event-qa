-- Data quality checks on StatsBomb event data.
-- Each view returns the rows that FAIL the check; an empty view means the check passed.
DROP SCHEMA IF EXISTS qa CASCADE;
CREATE SCHEMA qa;

-- 1. Goals in the event stream must match the official score.
--    Own goals count for the benefiting team ('Own Goal For'); penalty shootout (period 5) is excluded.
CREATE VIEW qa.goal_mismatch AS
WITH event_goals AS (
    SELECT match_id, team_id, count(*) AS goals
    FROM events
    WHERE period < 5
      AND ((type = 'Shot' AND shot_outcome = 'Goal') OR type = 'Own Goal For')
    GROUP BY match_id, team_id
)
SELECT m.match_id, m.home_team, m.away_team,
       m.home_score, coalesce(h.goals, 0) AS home_from_events,
       m.away_score, coalesce(a.goals, 0) AS away_from_events
FROM matches m
LEFT JOIN event_goals h ON h.match_id = m.match_id AND h.team_id = m.home_team_id
LEFT JOIN event_goals a ON a.match_id = m.match_id AND a.team_id = m.away_team_id
WHERE m.home_score <> coalesce(h.goals, 0) OR m.away_score <> coalesce(a.goals, 0);

-- 2. A sent-off player must not appear in any later on-pitch event.
CREATE VIEW qa.events_after_red_card AS
SELECT c.match_id, c.player_id, c.card, c.minute AS card_minute, e.idx, e.minute, e.type
FROM events c
JOIN events e ON e.match_id = c.match_id AND e.player_id = c.player_id AND e.idx > c.idx
WHERE c.card IN ('Red Card', 'Second Yellow')
  AND e.type NOT IN ('Substitution', 'Player Off', 'Bad Behaviour');

-- 3. A substitute must not have events before coming on; a replaced player none after going off.
CREATE VIEW qa.events_outside_sub_window AS
WITH subs AS (
    SELECT match_id, idx, minute, player_id AS player_off,
           (raw -> 'substitution' -> 'replacement' ->> 'id')::int AS player_on
    FROM events
    WHERE type = 'Substitution'
)
SELECT s.match_id, 'before coming on' AS issue, s.player_on AS player_id,
       s.minute AS sub_minute, e.minute, e.type
FROM subs s
JOIN events e ON e.match_id = s.match_id AND e.player_id = s.player_on AND e.idx < s.idx
WHERE e.type <> 'Bad Behaviour'
UNION ALL
SELECT s.match_id, 'after going off', s.player_off, s.minute, e.minute, e.type
FROM subs s
JOIN events e ON e.match_id = s.match_id AND e.player_id = s.player_off AND e.idx > s.idx
WHERE e.type <> 'Bad Behaviour';

-- 4. A pass recipient must be in the passer's own team lineup.
CREATE VIEW qa.bad_pass_recipient AS
SELECT e.match_id, e.idx, e.minute, e.team_id, e.player_id, e.pass_recipient_id,
       l.team_id AS recipient_team_id
FROM events e
LEFT JOIN lineups l ON l.match_id = e.match_id AND l.player_id = e.pass_recipient_id
WHERE e.type = 'Pass'
  AND e.pass_recipient_id IS NOT NULL
  AND l.team_id IS DISTINCT FROM e.team_id;

-- 5. All coordinates must lie on the 120 x 80 StatsBomb pitch.
CREATE VIEW qa.location_out_of_bounds AS
SELECT match_id, idx, minute, type, x, y, end_x, end_y
FROM events
WHERE x NOT BETWEEN 0 AND 120 OR y NOT BETWEEN 0 AND 80
   OR end_x NOT BETWEEN 0 AND 120 OR end_y NOT BETWEEN 0 AND 80;

-- 6. Every related event must exist and belong to the same match.
CREATE VIEW qa.broken_related_events AS
SELECT e.match_id, e.idx, e.type, r.related_id
FROM events e
CROSS JOIN LATERAL unnest(e.related_events) AS r(related_id)
LEFT JOIN events t ON t.id = r.related_id
WHERE t.id IS NULL OR t.match_id <> e.match_id;

-- 7. Within a period, event time should not jump backwards by more than 1 second.
CREATE VIEW qa.time_goes_backwards AS
SELECT match_id, period, idx, type, ts, prev_ts
FROM (
    SELECT match_id, period, idx, type, ts,
           lag(ts) OVER (PARTITION BY match_id, period ORDER BY idx) AS prev_ts
    FROM events
) t
WHERE prev_ts - ts > interval '1 second';

-- 8. Every shot must have an xG value, a location and an outcome.
CREATE VIEW qa.incomplete_shots AS
SELECT match_id, idx, minute, player_id, shot_xg, x, y, shot_outcome
FROM events
WHERE type = 'Shot' AND (shot_xg IS NULL OR x IS NULL OR shot_outcome IS NULL);

-- Summary: one row per check.
CREATE VIEW qa.summary AS
SELECT '1 goal_mismatch' AS check_name, count(*) AS failures FROM qa.goal_mismatch
UNION ALL SELECT '2 events_after_red_card', count(*) FROM qa.events_after_red_card
UNION ALL SELECT '3 events_outside_sub_window', count(*) FROM qa.events_outside_sub_window
UNION ALL SELECT '4 bad_pass_recipient', count(*) FROM qa.bad_pass_recipient
UNION ALL SELECT '5 location_out_of_bounds', count(*) FROM qa.location_out_of_bounds
UNION ALL SELECT '6 broken_related_events', count(*) FROM qa.broken_related_events
UNION ALL SELECT '7 time_goes_backwards', count(*) FROM qa.time_goes_backwards
UNION ALL SELECT '8 incomplete_shots', count(*) FROM qa.incomplete_shots
ORDER BY check_name;
