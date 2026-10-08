DROP TABLE IF EXISTS events, lineups, matches CASCADE;

CREATE TABLE matches (
    match_id        integer PRIMARY KEY,
    competition_id  integer NOT NULL,
    season_id       integer NOT NULL,
    match_date      date NOT NULL,
    stage           text,
    home_team_id    integer NOT NULL,
    home_team       text NOT NULL,
    away_team_id    integer NOT NULL,
    away_team       text NOT NULL,
    home_score      smallint NOT NULL,
    away_score      smallint NOT NULL
);

CREATE TABLE lineups (
    match_id     integer REFERENCES matches ON DELETE CASCADE,
    team_id      integer NOT NULL,
    player_id    integer NOT NULL,
    player_name  text NOT NULL,
    jersey       smallint,
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE events (
    id                 uuid PRIMARY KEY,
    match_id           integer NOT NULL REFERENCES matches ON DELETE CASCADE,
    idx                integer NOT NULL,          -- order of the event within the match
    period             smallint NOT NULL,         -- 1-2 regular, 3-4 extra time, 5 penalty shootout
    ts                 interval NOT NULL,         -- time since start of the period
    minute             smallint NOT NULL,
    second             smallint NOT NULL,
    type               text NOT NULL,
    possession         integer,
    possession_team_id integer,
    play_pattern       text,
    team_id            integer,
    player_id          integer,
    position           text,
    x                  numeric(5,2),              -- StatsBomb pitch is 120 x 80
    y                  numeric(5,2),
    end_x              numeric(5,2),
    end_y              numeric(5,2),
    under_pressure     boolean NOT NULL DEFAULT false,
    related_events     uuid[],
    pass_recipient_id  integer,
    pass_outcome       text,                      -- NULL means the pass was completed
    shot_outcome       text,
    shot_xg            numeric(6,5),
    shot_body_part     text,
    shot_type          text,
    card               text,
    raw                jsonb NOT NULL,
    UNIQUE (match_id, idx)
);

CREATE INDEX ON events (match_id, type);
CREATE INDEX ON events (player_id);
