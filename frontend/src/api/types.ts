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
  status: string
  nba_game_id: string
}

export interface PlayerGameStatRead {
  id: number
  game_id: number
  nba_game_id: string
  game_date: ISODateString
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

export type ParlayMode = 'standard' | 'x_of_y'

export type StatType = 'PTS' | 'REB' | 'AST'

export type LegDirection = 'OVER' | 'UNDER'

export interface LegIn {
  player_id: number
  game_id: number | null
  stat_type: StatType
  line: number
  direction: LegDirection
}

export interface ParlayCreate {
  mode: ParlayMode
  k_required?: number | null
  wager_on_hit?: boolean
  lookback_games?: number
  simulation_iterations?: number
  rng_seed?: number | null
  legs: LegIn[]
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
  p_miss?: number | null
  p_ticket?: number | null
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
