-- Team-level analytics on StatsBomb event data.
-- StatsBomb coordinates are oriented per acting team: every team attacks left to right, x = 0 is its own goal line.
CREATE SCHEMA IF NOT EXISTS analytics;

-- PPDA (passes allowed per defensive action): lower = more intense pressing.
-- Opponent open-play passes in their own 60% of the pitch / our defensive actions in that same zone.
CREATE OR REPLACE VIEW analytics.team_ppda AS
WITH team_match AS (
    SELECT match_id, home_team_id AS team_id, home_team AS team, away_team_id AS opp_id FROM matches
    UNION ALL
    SELECT match_id, away_team_id, away_team, home_team_id FROM matches
),
opp_passes AS (
    SELECT tm.team, count(*) AS n
    FROM team_match tm
    JOIN events e ON e.match_id = tm.match_id AND e.team_id = tm.opp_id
    WHERE e.type = 'Pass' AND e.period < 5 AND e.x < 72
      AND coalesce(e.raw -> 'pass' -> 'type' ->> 'name', '')
          NOT IN ('Corner', 'Free Kick', 'Throw-in', 'Goal Kick', 'Kick Off')
    GROUP BY tm.team
),
def_actions AS (
    SELECT tm.team, count(*) AS n
    FROM team_match tm
    JOIN events e ON e.match_id = tm.match_id AND e.team_id = tm.team_id
    WHERE e.period < 5 AND e.x > 48
      AND (e.type IN ('Interception', 'Foul Committed', 'Dribbled Past')
           OR (e.type = 'Duel' AND e.raw -> 'duel' -> 'type' ->> 'name' = 'Tackle'))
    GROUP BY tm.team
),
games AS (
    SELECT team, count(*) AS matches FROM team_match GROUP BY team
)
SELECT g.team, g.matches, p.n AS opp_passes, d.n AS def_actions,
       round(p.n::numeric / d.n, 2) AS ppda
FROM games g
JOIN opp_passes p USING (team)
JOIN def_actions d USING (team)
ORDER BY ppda;
