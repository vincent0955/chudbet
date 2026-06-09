/**
 * Deterministic backend fixtures used by the API mock layer.
 *
 * Dates are far in the future so the home-page "upcoming games" filter always
 * treats the slate as bettable, independent of when the suite runs.
 */

export const ACCOUNT_ID = 1
export const GAME_ID = 101
export const INITIAL_BALANCE_CENTS = 5_000_000 // $50,000.00

export const FUTURE_DATE = '2099-01-15'
export const FUTURE_TIP_UTC = '2099-01-15T23:30:00Z'

export const AWAY_TEAM = { id: 2, name: 'Los Angeles Lakers', nba_team_id: 1610612747 }
export const HOME_TEAM = { id: 1, name: 'Boston Celtics', nba_team_id: 1610612738 }

export const TEAMS = [HOME_TEAM, AWAY_TEAM]

export const GAME = {
  id: GAME_ID,
  home_team_id: HOME_TEAM.id,
  away_team_id: AWAY_TEAM.id,
  game_date: FUTURE_DATE,
  game_time_utc: FUTURE_TIP_UTC,
  home_score: null,
  away_score: null,
  status: 'Scheduled',
  nba_game_id: '0029900101',
}

export const GAMES = [GAME]

export const PLAYERS = [
  { id: 11, full_name: 'LeBron James', team_id: AWAY_TEAM.id, nba_player_id: 2544 },
  { id: 22, full_name: 'Jayson Tatum', team_id: HOME_TEAM.id, nba_player_id: 1628369 },
]

export const GAME_MARKETS = {
  game: GAME,
  lookback: 15,
  sample_games_home: 12,
  sample_games_away: 12,
  moneyline: { home_american: '-150', away_american: '+130' },
  spread: {
    home_line: -3.5,
    home_american: '-110',
    away_line: 3.5,
    away_american: '-110',
  },
  total: { line: 224.5, over_american: '-110', under_american: '-110' },
}

function propRow(
  player: { id: number; full_name: string; team_id: number; nba_player_id: number },
  ptsLine: number,
  rebLine: number,
  astLine: number,
  teamName: string,
  teamNbaId: number,
) {
  return {
    id: player.id,
    full_name: player.full_name,
    team_id: player.team_id,
    team_name: teamName,
    team_nba_id: teamNbaId,
    nba_player_id: player.nba_player_id,
    sample_size: 15,
    pts_line: ptsLine,
    reb_line: rebLine,
    ast_line: astLine,
    pts_over_american: '-110',
    pts_under_american: '-110',
    reb_over_american: '-110',
    reb_under_american: '-110',
    ast_over_american: '-110',
    ast_under_american: '-110',
  }
}

export const GAME_PROP_LINES = {
  game: GAME,
  lookback: 15,
  min_samples: 5,
  players: [
    propRow(PLAYERS[0], 27.5, 7.5, 8.5, AWAY_TEAM.name, AWAY_TEAM.nba_team_id),
    propRow(PLAYERS[1], 24.5, 8.5, 4.5, HOME_TEAM.name, HOME_TEAM.nba_team_id),
  ],
}

export const GUEST_USER = {
  id: 1,
  email: 'guest@example.com',
  username: 'guest-1',
  is_guest: true,
  created_at: '2099-01-01T00:00:00Z',
}

export const NAMED_USER = {
  id: 2,
  email: 'fan@example.com',
  username: 'hoopsfan',
  is_guest: false,
  created_at: '2099-01-01T00:00:00Z',
}

/** An open wager + matching detail (one player prop leg) for the My Bets "open" tab. */
export function openPendingWager() {
  const wager = {
    id: 9100,
    created_at: '2099-01-12T18:00:00Z',
    account_id: ACCOUNT_ID,
    parlay_id: 5100,
    stake_cents: 5_000,
    offered_decimal_odds: 1.9,
    potential_return_cents: 9_500,
    status: 'open' as const,
  }
  const detail = {
    wager,
    account: { id: ACCOUNT_ID, created_at: GUEST_USER.created_at, balance_cents: INITIAL_BALANCE_CENTS },
    duplicated: false,
    parlay: {
      id: 5100,
      created_at: wager.created_at,
      mode: 'standard' as const,
      k_required: null,
      total_legs: 1,
      p_hit: 0.5,
      wager_on_hit: true,
      fair_decimal_odds: 1.9,
      metadata_json: null,
      stake_cents: 5_000,
      payout_cents: 9_500,
      legs: [
        {
          id: 7100,
          player_id: PLAYERS[0].id,
          player_nba_id: PLAYERS[0].nba_player_id,
          player_team_nba_id: AWAY_TEAM.nba_team_id,
          game_id: GAME_ID,
          stat_type: 'PTS' as const,
          line: 27.5,
          direction: 'OVER' as const,
          leg_probability: 0.5,
          sort_order: 0,
          outcome: 'pending' as const,
          player_full_name: PLAYERS[0].full_name,
          game_label: `${AWAY_TEAM.name} @ ${HOME_TEAM.name}`,
          game_home_team_name: HOME_TEAM.name,
          game_away_team_name: AWAY_TEAM.name,
          game_home_score: null,
          game_away_score: null,
          game_date: FUTURE_DATE,
          game_time_utc: FUTURE_TIP_UTC,
          game_status: 'Scheduled',
          stat_value: null,
        },
      ],
      game_legs: [],
    },
  }
  return { wager, detail }
}

/** A settled (won) wager + matching detail used by the My Bets "settled" tab. */
export function settledWonWager() {
  const wager = {
    id: 9001,
    created_at: '2099-01-10T18:00:00Z',
    account_id: ACCOUNT_ID,
    parlay_id: 5001,
    stake_cents: 10_000,
    offered_decimal_odds: 2.5,
    potential_return_cents: 25_000,
    status: 'won' as const,
  }
  const detail = {
    wager,
    account: { id: ACCOUNT_ID, created_at: GUEST_USER.created_at, balance_cents: INITIAL_BALANCE_CENTS },
    duplicated: false,
    parlay: {
      id: 5001,
      created_at: wager.created_at,
      mode: 'standard' as const,
      k_required: null,
      total_legs: 1,
      p_hit: 0.4,
      wager_on_hit: true,
      fair_decimal_odds: 2.5,
      metadata_json: null,
      stake_cents: 10_000,
      payout_cents: 25_000,
      legs: [],
      game_legs: [
        {
          id: 7001,
          game_id: GAME_ID,
          market_type: 'moneyline' as const,
          selection: 'home' as const,
          line: null,
          odds_american: -150,
          leg_probability: 0.6,
          sort_order: 0,
          outcome: 'hit' as const,
          game_label: `${AWAY_TEAM.name} @ ${HOME_TEAM.name}`,
          home_team_name: HOME_TEAM.name,
          away_team_name: AWAY_TEAM.name,
          home_team_nba_id: HOME_TEAM.nba_team_id,
          away_team_nba_id: AWAY_TEAM.nba_team_id,
          home_score: 110,
          away_score: 100,
          game_date: FUTURE_DATE,
          game_time_utc: FUTURE_TIP_UTC,
          game_status: 'Final',
        },
      ],
    },
  }
  return { wager, detail }
}
