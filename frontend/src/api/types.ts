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
