# Database schema

This diagram matches the models under `backend/app/db/models/`

```mermaid
erDiagram
    teams {
        integer id PK
        integer nba_team_id UK "NOT NULL, indexed"
        varchar name "NOT NULL, len 255"
    }

    players {
        integer id PK
        integer nba_player_id UK "NOT NULL, indexed"
        varchar full_name "NOT NULL, len 255"
        integer team_id FK "NOT NULL"
    }

    games {
        integer id PK
        varchar nba_game_id UK "NOT NULL, len 16, indexed"
        integer home_team_id FK "NOT NULL"
        integer away_team_id FK "NOT NULL"
        date game_date "NOT NULL"
        varchar status "NOT NULL, len 64"
    }

    player_game_stats {
        integer id PK
        integer player_id FK "NOT NULL, indexed"
        integer game_id FK "NOT NULL, indexed"
        integer points "NOT NULL, default 0"
        integer rebounds "NOT NULL, default 0"
        integer assists "NOT NULL, default 0"
        float minutes "NOT NULL, default 0.0"
    }

    parlays {
        integer id PK
        timestamptz created_at "NOT NULL, default now"
        varchar mode "NOT NULL standard|x_of_y"
        integer k_required "nullable; X-of-Y only"
        integer total_legs "NOT NULL"
        float p_hit "nullable; DB column joint_probability"
        boolean wager_on_hit "NOT NULL default true"
        float fair_decimal_odds "nullable; fair odds for wager taken"
        json metadata_json "nullable"
    }

    parlay_legs {
        integer id PK
        integer parlay_id FK "NOT NULL, indexed, CASCADE"
        integer player_id FK "NOT NULL, indexed"
        integer game_id FK "nullable, indexed"
        varchar stat_type "NOT NULL PTS|REB|AST"
        float line "NOT NULL"
        varchar direction "NOT NULL OVER|UNDER"
        float leg_probability "NOT NULL"
        integer sort_order "NOT NULL"
    }

    teams ||--o{ players : "has"
    teams ||--o{ games : "home_team"
    teams ||--o{ games : "away_team"
    players ||--o{ player_game_stats : "stats"
    games ||--o{ player_game_stats : "stats"
    parlays ||--o{ parlay_legs : "has"
    players ||--o{ parlay_legs : "leg_player"
    games ||--o{ parlay_legs : "optional_game"
```



## Notes

- `games` references `teams` twice: `home_team_id` and `away_team_id` are separate foreign keys to `teams.id`.
- `player_game_stats` has btree indexes on `player_id` and `game_id`, and a **unique constraint** on `(player_id, game_id)`.
- NBA identifiers (`nba_team_id`, `nba_player_id`, `nba_game_id`) support idempotent ingestion from `nba_api`.
- **`parlays` / `parlay_legs`** are application-defined (not filled by NBA ingestion). Enum-like columns use **VARCHAR** (`native_enum=False`). Check constraints: `x_of_y` requires valid `k_required`; `standard` keeps `k_required` null.
- **`p_hit`** is always **P(parlay hits)** (physical column name remains **`joint_probability`** in Postgres for older DBs). **`wager_on_hit`** selects for vs against; **`fair_decimal_odds`** is **1 / P(ticket wins)** (anti uses **1 − p_hit** for the ticket).
- `parlay_legs.game_id` is optional so legs can target a player without a scheduled row yet.
- Unique `(parlay_id, sort_order)` on `parlay_legs`.

