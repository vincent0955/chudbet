import type { ParlayLegRead } from '../api/types'
import { mlbPlayerHeadshotUrl, mlbTeamLogoUrl } from './mlbMedia'
import { nbaPlayerHeadshotUrl, nbaTeamLogoUrl } from './nbaMedia'

type ParlayLegMediaIds = Pick<
  ParlayLegRead,
  'player_nba_id' | 'player_mlb_id' | 'player_team_nba_id' | 'player_team_mlb_id'
>

/** Headshot URL for a parlay player leg (NBA or MLB native id). */
export function parlayLegPlayerHeadshotUrl(leg: ParlayLegMediaIds): string | null {
  return nbaPlayerHeadshotUrl(leg.player_nba_id) ?? mlbPlayerHeadshotUrl(leg.player_mlb_id)
}

/** Team badge URL for a parlay player leg (NBA or MLB native id). */
export function parlayLegPlayerTeamLogoUrl(leg: ParlayLegMediaIds): string | null {
  return nbaTeamLogoUrl(leg.player_team_nba_id) ?? mlbTeamLogoUrl(leg.player_team_mlb_id)
}
