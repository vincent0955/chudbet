/** ISO date string from JSON (`YYYY-MM-DD`). */
export type ISODateString = string

export interface TeamRead {
  id: number
  name: string
  nba_team_id: number
}

export interface PlayerRead {
  id: number
  full_name: string
  team_id: number
  nba_player_id: number
}

export interface GameRead {
  id: number
  home_team_id: number
  away_team_id: number
  game_date: ISODateString
  /** Tip-off from NBA scoreboard (UTC ISO), when known. */
  game_time_utc?: string | null
  home_score?: number | null
  away_score?: number | null
  status: string
  nba_game_id: string
}

export interface PlayerGameStatRead {
  id: number
  game_id: number
  nba_game_id: string
  game_date: ISODateString
  game_time_utc?: string | null
  /** NBA-derived schedule/status text (home page meta); often tip time before tip-off. */
  game_status: string
  points: number
  rebounds: number
  assists: number
  minutes: number
}

/** Server-aggregated rolling-average lines for PTS / REB / AST for one game. */
export interface PlayerPropLinesRead {
  id: number
  full_name: string
  team_id: number
  team_name: string
  nba_player_id: number
  sample_size: number
  pts_line: number | null
  reb_line: number | null
  ast_line: number | null
  /** Placeholder American odds strings, e.g. "-110". */
  pts_over_american: string
  pts_under_american: string
  reb_over_american: string
  reb_under_american: string
  ast_over_american: string
  ast_under_american: string
}

export interface GamePropLinesBundle {
  game: GameRead
  lookback: number
  min_samples: number
  players: PlayerPropLinesRead[]
}

export interface GameMarketsRead {
  game: GameRead
  lookback: number
  sample_games_home: number
  sample_games_away: number
  moneyline: {
    home_american: string
    away_american: string
  }
  spread: {
    home_line: number
    home_american: string
    away_line: number
    away_american: string
  }
  total: {
    line: number
    over_american: string
    under_american: string
  }
}

export type ParlayMode = 'standard' | 'x_of_y'

export type StatType = 'PTS' | 'REB' | 'AST'

export type LegDirection = 'OVER' | 'UNDER'
export type GameMarketType = 'moneyline' | 'spread' | 'total'
export type GameSelection = 'home' | 'away' | 'over' | 'under'

export type ParlayLegOutcome = 'pending' | 'hit' | 'miss' | 'void'

export interface LegIn {
  player_id: number
  game_id: number | null
  stat_type: StatType
  line: number
  direction: LegDirection
}

export interface GameLegIn {
  game_id: number
  market_type: GameMarketType
  selection: GameSelection
  line?: number | null
  odds_american: number
}

export interface ParlayCreate {
  mode: ParlayMode
  k_required?: number | null
  wager_on_hit?: boolean
  lookback_games?: number
  simulation_iterations?: number
  rng_seed?: number | null
  legs: LegIn[]
  game_legs?: GameLegIn[]
}

export interface ParlayLegRead {
  id: number
  player_id: number
  game_id: number | null
  stat_type: StatType
  line: number
  direction: LegDirection
  leg_probability: number
  sort_order: number
  outcome?: ParlayLegOutcome | null
  player_full_name?: string | null
}

export interface ParlayRead {
  id: number
  created_at: string
  mode: ParlayMode
  k_required: number | null
  total_legs: number
  p_hit: number | null
  wager_on_hit: boolean
  fair_decimal_odds: number | null
  metadata_json: Record<string, unknown> | null
  legs: ParlayLegRead[]
  game_legs?: ParlayGameLegRead[]
  p_miss?: number | null
  p_ticket?: number | null
}

export interface ParlayGameLegRead {
  id: number
  game_id: number
  market_type: GameMarketType
  selection: GameSelection
  line: number | null
  odds_american: number
  leg_probability: number
  sort_order: number
  outcome?: ParlayLegOutcome | null
}

export interface HealthResponse {
  status: string
}

export interface AccountRead {
  id: number
  /** ISO timestamps from Postgres timestamptz. */
  created_at: string
  balance_cents: number
}

export type WagerStatus = 'open' | 'won' | 'lost' | 'void' | 'cancelled'

export interface WagerRead {
  id: number
  created_at: string
  account_id: number
  parlay_id: number
  stake_cents: number
  offered_decimal_odds: number
  potential_return_cents: number
  status: WagerStatus
}

export interface WagerPlaceBody {
  stake_cents: number
  offered_decimal_odds?: number | null
  idempotency_key?: string | null
  parlay: ParlayCreate
}

export interface WagerDetailResponse {
  wager: WagerRead
  account: AccountRead
  parlay: ParlayRead
  duplicated: boolean
}
