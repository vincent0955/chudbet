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

    accounts {
        integer id PK
        timestamptz created_at "NOT NULL, default now"
        bigint balance_cents "NOT NULL, default 0"
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
    accounts ||--o{ ledger_entries : "journal"
    accounts ||--o{ wagers : "places"
    wagers }|--|| parlays : "backs_snapshot"
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

### Money (accounts / ledger / wagers)

- **`accounts`** holds a cached **`balance_cents`** (bigint). Application code adjusts it **only** in the same DB transaction as an appended **`ledger_entries`** row; negative **`amount_cents`** are debits, positive credits.
- **`ledger_entries.reference_type`** / **`reference_id`** link postings to domain rows (e.g. **`wager`** + wager id). Optional **`idempotency_key`** is globally **UNIQUE** for safe **`POST`** replay (especially deposits).
- Composite index **`ix_ledger_entries_account_created`** on **`(account_id, created_at)`** supports recent-history queries by account.
- **`wagers`** is the financed ticket at a **priced** payout multiple: **`offered_decimal_odds`** and **`potential_return_cents`** (typically `round(stake_cents × odds)`). Exactly **one wager per parlay** is enforced by **`uq_wagers_parlay_id`**; **`parlays` rows created via `POST /parlays` alone have no wager. **`ON DELETE RESTRICT`** on **`wagers`** → **`parlays`** avoids deleting math snapshots while money rows exist (settlement workflows should flip **`status`** instead of hard-deleting **`parlays`**).
- **`Wager.status`** lifecycle **`open`** → **`won` / `lost` / `void` / `cancelled`** is reserved for grading/cashout logic; extra ledger types (**`wager_payout`**, **`wager_void`**, **`adjustment`**) exist for future settlement.
- **`wagers.idempotency_key`** is optional and **UNIQUE** for idempotent wager placement (**`POST /accounts/{id}/wagers`**).

