# Database schema

PostgreSQL tables shared across sports. Each sport-scoped row carries a `sport`
column (`NBA` or `MLB`) and exactly one native external ID (`nba_*` or `mlb_*`).

```mermaid
erDiagram
    teams {
        integer id PK
        varchar sport "NOT NULL NBA|MLB default NBA"
        integer nba_team_id "nullable, partial unique when set"
        integer mlb_team_id "nullable, partial unique when set"
        varchar name "NOT NULL, len 255"
        varchar abbreviation "nullable, len 16"
    }

    players {
        integer id PK
        varchar sport "NOT NULL NBA|MLB default NBA"
        integer nba_player_id "nullable, partial unique when set"
        integer mlb_player_id "nullable, partial unique when set"
        varchar full_name "NOT NULL, len 255"
        integer team_id FK "NOT NULL"
        varchar primary_position "nullable, len 32"
    }

    games {
        integer id PK
        varchar sport "NOT NULL NBA|MLB default NBA"
        varchar nba_game_id "nullable, len 16, partial unique when set"
        varchar mlb_game_id "nullable, len 16, partial unique when set"
        integer home_team_id FK "NOT NULL"
        integer away_team_id FK "NOT NULL"
        date game_date "NOT NULL"
        timestamptz game_time_utc "NULL"
        integer home_score "NULL"
        integer away_score "NULL"
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

    mlb_player_game_stats {
        integer id PK
        integer player_id FK "NOT NULL, indexed"
        integer game_id FK "NOT NULL, indexed"
        integer hits "NOT NULL, default 0, CHECK >= 0"
        integer total_bases "NOT NULL, default 0, CHECK >= 0"
        integer rbi "NOT NULL, default 0, CHECK >= 0"
        integer runs "NOT NULL, default 0, CHECK >= 0"
        integer strikeouts_pitcher "NOT NULL, default 0, CHECK >= 0"
    }

    accounts {
        integer id PK
        timestamptz created_at "NOT NULL, default now"
        bigint balance_cents "NOT NULL, default 0"
        integer user_id FK "nullable, indexed, SET NULL on delete"
    }

    users {
        integer id PK
        varchar email "NOT NULL, UNIQUE, len 320"
        varchar username "NOT NULL, UNIQUE, len 64"
        varchar password_hash "NOT NULL, len 512"
        boolean is_guest "NOT NULL, default false"
        timestamptz created_at "NOT NULL, default now"
    }

    user_sessions {
        integer id PK
        integer user_id FK "NOT NULL, indexed, CASCADE delete"
        varchar token_hash "NOT NULL, UNIQUE, indexed, len 128"
        varchar user_agent "nullable, len 512"
        timestamptz created_at "NOT NULL, default now"
        timestamptz expires_at "NOT NULL, indexed"
        timestamptz revoked_at "nullable"
    }

    ledger_entries {
        integer id PK
        timestamptz created_at "NOT NULL, default now"
        integer account_id FK "NOT NULL, indexed, CASCADE delete"
        varchar entry_type "NOT NULL deposit|wager_stake|wager_payout|wager_void|adjustment"
        bigint amount_cents "NOT NULL, signed debit negative"
        bigint balance_after_cents "NOT NULL"
        varchar reference_type "nullable, len 32 e.g wager"
        integer reference_id "nullable"
        varchar idempotency_key "nullable, UNIQUE len 72"
        varchar memo "nullable, len 512"
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

    wagers {
        integer id PK
        timestamptz created_at "NOT NULL, default now"
        integer account_id FK "NOT NULL, indexed, RESTRICT delete"
        integer parlay_id FK "NOT NULL, UNIQUE uk_wagers_parlay_id, RESTRICT delete"
        bigint stake_cents "NOT NULL, CHECK positive"
        float offered_decimal_odds "NOT NULL, CHECK gt 1"
        bigint potential_return_cents "NOT NULL, rounded stake times odds"
        varchar status "NOT NULL open|won|lost|void|cancelled"
        varchar idempotency_key "nullable, UNIQUE len 72"
    }

    parlay_legs {
        integer id PK
        integer parlay_id FK "NOT NULL, indexed, CASCADE"
        integer player_id FK "NOT NULL, indexed"
        integer game_id FK "nullable, indexed"
        varchar stat_type "NOT NULL see Player props below"
        float line "NOT NULL"
        varchar direction "NOT NULL OVER|UNDER"
        float leg_probability "NOT NULL"
        integer sort_order "NOT NULL"
        varchar outcome_status "NOT NULL pending|hit|miss|void default pending"
    }

    parlay_game_legs {
        integer id PK
        integer parlay_id FK "NOT NULL, indexed, CASCADE"
        integer game_id FK "NOT NULL, indexed"
        varchar market_type "NOT NULL moneyline|spread|total"
        varchar selection "NOT NULL home|away|over|under"
        float line "nullable"
        integer odds_american "NOT NULL"
        float leg_probability "NOT NULL"
        integer sort_order "NOT NULL"
        varchar outcome_status "NOT NULL pending|hit|miss|void default pending"
    }

    teams ||--o{ players : "has"
    teams ||--o{ games : "home_team"
    teams ||--o{ games : "away_team"
    players ||--o{ player_game_stats : "nba_stats"
    games ||--o{ player_game_stats : "nba_stats"
    players ||--o{ mlb_player_game_stats : "mlb_stats"
    games ||--o{ mlb_player_game_stats : "mlb_stats"
    users ||--o{ accounts : "owns_wallets"
    users ||--o{ user_sessions : "has_sessions"
    accounts ||--o{ ledger_entries : "journal"
    accounts ||--o{ wagers : "places"
    wagers }|--|| parlays : "backs_snapshot"
    parlays ||--o{ parlay_legs : "has"
    parlays ||--o{ parlay_game_legs : "has_game_legs"
    players ||--o{ parlay_legs : "leg_player"
    games ||--o{ parlay_legs : "optional_game"
    games ||--o{ parlay_game_legs : "market_game"
```

## Sport scoping

| Table   | Constraint |
|---------|------------|
| `teams` | `sport = 'NBA'` requires `nba_team_id` and forbids `mlb_team_id`; `sport = 'MLB'` is the mirror. |
| `players` | Same pattern with `nba_player_id` / `mlb_player_id`. |
| `games` | Same pattern with `nba_game_id` / `mlb_game_id`. |

Box-score stats are split by sport:

- **NBA** — `player_game_stats` (`points`, `rebounds`, `assists`, `minutes`)
- **MLB** — `mlb_player_game_stats` (`hits`, `total_bases`, `rbi`, `runs`, `strikeouts_pitcher`)

Settlement reads the appropriate table based on `games.sport`.

## Player props

### `parlay_legs` encoding

Both sports persist player-prop legs in `parlay_legs`. The `stat_type`, `line`, and
`direction` columns are interpreted by the sport of the referenced `game_id`.

| Sport | `stat_type` values | Market shape |
|-------|-------------------|--------------|
| NBA | `PTS`, `REB`, `AST` | Single half-point over/under line (e.g. `24.5` OVER / UNDER) |
| MLB | `HITS`, `TOTAL_BASES`, `RBI`, `RUNS`, `STRIKEOUTS_PITCHER` | **Milestone ladder** — see below |

MLB milestone picks are stored as **`direction = OVER`** with **`line = threshold − 0.5`**
so existing settlement (`actual > line`) grades “N or more” correctly:

| User-facing pick | `line` | `direction` | Grades as |
|------------------|--------|-------------|-----------|
| 1+ hits | `0.5` | `OVER` | `hits >= 1` |
| 2+ hits | `1.5` | `OVER` | `hits >= 2` |
| 3+ hits | `2.5` | `OVER` | `hits >= 3` |

The `UNDER` direction remains valid in the schema but is not offered in the MLB UI;
NBA continues to use both sides.

### MLB prop API (`GET /mlb/games/{id}/props`)

Not stored in the database — computed at request time from rolling
`mlb_player_game_stats` — but returned as:

```
MLBGamePropLinesBundle
├── game: MLBGameRead
├── lookback_days: int
├── min_samples: int
└── players: MLBPlayerPropLinesRead[]
    ├── id, full_name, team_id, team_name, …
    ├── sample_size: int
    └── stat_lines: MLBPropStatLineRead[]
        ├── stat_type: HITS | TOTAL_BASES | RBI | RUNS | STRIKEOUTS_PITCHER
        └── thresholds: MLBPropThresholdRead[]   # always 1+, 2+, 3+ when offered
            ├── threshold: 1 | 2 | 3
            ├── line: 0.5 | 1.5 | 2.5          # wager-leg encoding
            ├── american: string                 # price for "N+" (yes)
            └── under_american: string           # complementary no side (pricer only)
```

**Pricing model**

Each milestone’s fair probability is `P(X ≥ threshold)` for a Poisson distribution
whose rate λ is the player’s rolling per-game average of that stat. The house margin
is applied to the two-way (reaches / does-not-reach) market per milestone. The pricer
selects the milestone matching the client’s `line`, de-vigs `american` / `under_american`,
and applies the ticket-level margin once at parlay aggregation
