import type { Page, Route } from '@playwright/test'
import type {
  AccountRead,
  AuthMeRead,
  GameLegIn,
  LegIn,
  ParlayGameLegRead,
  ParlayLegRead,
  ParlayRead,
  UserRead,
  WagerDetailResponse,
  WagerPlaceBody,
  WagerRead,
} from '../../src/api/types'
import {
  ACCOUNT_ID,
  GAME,
  GAME_MARKETS,
  GAME_PROP_LINES,
  GAMES,
  GUEST_USER,
  INITIAL_BALANCE_CENTS,
  NAMED_USER,
  PLAYERS,
  TEAMS,
} from './fixtures'

const API_ORIGIN = 'http://localhost:8000'

type JsonBody = Record<string, unknown> | unknown[] | null

type MockState = {
  loggedIn: boolean
  user: UserRead
  balanceCents: number
  wagers: WagerRead[]
  wagerDetails: Record<number, WagerDetailResponse>
  nextWagerId: number
  nextParlayId: number
}

export type ApiMock = {
  state: MockState
  /** Number of times a wager-place POST was received. */
  placedCount: () => number
}

type InstallOptions = {
  /** Start already authenticated (skip the guest-login click). */
  loggedIn?: boolean
  /** Seed wagers + their detail responses. */
  seedWagers?: { wager: WagerRead; detail: WagerDetailResponse }[]
}

function json(route: Route, status: number, data: JsonBody) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(data),
  })
}

function account(state: MockState): AccountRead {
  return { id: ACCOUNT_ID, created_at: state.user.created_at, balance_cents: state.balanceCents }
}

function authMePayload(state: MockState): AuthMeRead {
  return {
    user: state.user,
    account_id: ACCOUNT_ID,
    balance_cents: state.balanceCents,
  }
}

function playerName(playerId: number): string {
  return PLAYERS.find((p) => p.id === playerId)?.full_name ?? `Player #${playerId}`
}

function buildParlayFromBody(body: WagerPlaceBody, parlayId: number): ParlayRead {
  const parlay = body.parlay
  const matchup = `${TEAMS[1].name} @ ${TEAMS[0].name}`
  const legs: ParlayLegRead[] = (parlay.legs ?? []).map((leg: LegIn, i) => ({
    id: 8000 + i,
    player_id: leg.player_id,
    player_nba_id: PLAYERS.find((p) => p.id === leg.player_id)?.nba_player_id ?? null,
    player_team_nba_id: null,
    game_id: leg.game_id ?? null,
    stat_type: leg.stat_type,
    line: leg.line,
    direction: leg.direction,
    leg_probability: 0.5,
    sort_order: i,
    outcome: 'pending',
    player_full_name: playerName(leg.player_id),
    game_label: matchup,
    game_home_team_name: TEAMS[0].name,
    game_away_team_name: TEAMS[1].name,
    game_home_score: null,
    game_away_score: null,
    game_date: GAME.game_date,
    game_time_utc: GAME.game_time_utc,
    game_status: GAME.status,
    stat_value: null,
  }))
  const gameLegs: ParlayGameLegRead[] = (parlay.game_legs ?? []).map((leg: GameLegIn, i) => ({
    id: 8500 + i,
    game_id: leg.game_id,
    market_type: leg.market_type,
    selection: leg.selection,
    line: leg.line ?? null,
    odds_american: leg.odds_american,
    leg_probability: 0.5,
    sort_order: legs.length + i,
    outcome: 'pending',
    game_label: matchup,
    home_team_name: TEAMS[0].name,
    away_team_name: TEAMS[1].name,
    home_team_nba_id: TEAMS[0].nba_team_id,
    away_team_nba_id: TEAMS[1].nba_team_id,
    home_score: null,
    away_score: null,
    game_date: GAME.game_date,
    game_time_utc: GAME.game_time_utc,
    game_status: GAME.status,
  }))
  return {
    id: parlayId,
    created_at: new Date().toISOString(),
    mode: parlay.mode ?? 'standard',
    k_required: parlay.k_required ?? null,
    total_legs: legs.length + gameLegs.length,
    p_hit: 0.42,
    wager_on_hit: parlay.wager_on_hit ?? true,
    fair_decimal_odds: body.offered_decimal_odds ?? 2.0,
    metadata_json: null,
    legs,
    game_legs: gameLegs,
  }
}

export async function installApiMocks(page: Page, options: InstallOptions = {}): Promise<ApiMock> {
  const state: MockState = {
    loggedIn: options.loggedIn ?? false,
    user: GUEST_USER,
    balanceCents: INITIAL_BALANCE_CENTS,
    wagers: [],
    wagerDetails: {},
    nextWagerId: 1000,
    nextParlayId: 2000,
  }

  for (const seed of options.seedWagers ?? []) {
    state.wagers.push(seed.wager)
    state.wagerDetails[seed.wager.id] = seed.detail
  }

  let placed = 0

  await page.route(`${API_ORIGIN}/**`, async (route) => {
    const request = route.request()
    const method = request.method()
    const { pathname } = new URL(request.url())

    // ---- Health ----
    if (pathname === '/health') return json(route, 200, { status: 'ok' })

    // ---- Auth ----
    if (pathname === '/auth/me') {
      if (!state.loggedIn) return json(route, 401, { detail: 'Not authenticated' })
      return json(route, 200, authMePayload(state))
    }
    if (pathname === '/auth/guest' && method === 'POST') {
      state.loggedIn = true
      state.user = GUEST_USER
      return json(route, 200, authMePayload(state))
    }
    if (pathname === '/auth/login' && method === 'POST') {
      state.loggedIn = true
      state.user = NAMED_USER
      return json(route, 200, authMePayload(state))
    }
    if (pathname === '/auth/signup' && method === 'POST') {
      const body = (request.postDataJSON?.() ?? {}) as { email?: string; username?: string }
      state.loggedIn = true
      state.user = {
        ...NAMED_USER,
        email: body.email ?? NAMED_USER.email,
        username: body.username ?? NAMED_USER.username,
      }
      return json(route, 200, authMePayload(state))
    }
    if (pathname === '/auth/logout' && method === 'POST') {
      state.loggedIn = false
      return json(route, 200, null)
    }

    // ---- Accounts / money ----
    if (pathname === `/accounts/${ACCOUNT_ID}` && method === 'GET') {
      return json(route, 200, account(state))
    }
    if (pathname === `/accounts/${ACCOUNT_ID}/deposit` && method === 'POST') {
      const body = (request.postDataJSON?.() ?? {}) as { amount_cents?: number }
      state.balanceCents += Number(body.amount_cents ?? 0)
      return json(route, 200, { account: account(state), ledger_entry_id: 1, duplicated: false })
    }
    if (pathname === `/accounts/${ACCOUNT_ID}/wagers` && method === 'POST') {
      placed += 1
      const body = (request.postDataJSON?.() ?? {}) as WagerPlaceBody
      const stake = Number(body.stake_cents ?? 0)
      const odds = Number(body.offered_decimal_odds ?? 2.0)
      const wagerId = state.nextWagerId++
      const parlayId = state.nextParlayId++
      const wager: WagerRead = {
        id: wagerId,
        created_at: new Date().toISOString(),
        account_id: ACCOUNT_ID,
        parlay_id: parlayId,
        stake_cents: stake,
        offered_decimal_odds: odds,
        potential_return_cents: Math.round(stake * odds),
        status: 'open',
      }
      const parlay = buildParlayFromBody(body, parlayId)
      state.balanceCents -= stake
      const detail: WagerDetailResponse = {
        wager,
        account: account(state),
        duplicated: false,
        parlay: { ...parlay, stake_cents: stake, payout_cents: wager.potential_return_cents },
      }
      state.wagers.unshift(wager)
      state.wagerDetails[wagerId] = detail
      return json(route, 201, detail)
    }
    if (pathname === `/accounts/${ACCOUNT_ID}/wagers` && method === 'GET') {
      return json(route, 200, state.wagers)
    }
    const wagerDetailMatch = pathname.match(new RegExp(`^/accounts/${ACCOUNT_ID}/wagers/(\\d+)$`))
    if (wagerDetailMatch && method === 'GET') {
      const id = Number(wagerDetailMatch[1])
      const detail = state.wagerDetails[id]
      if (!detail) return json(route, 404, { detail: 'wager not found' })
      return json(route, 200, detail)
    }

    // ---- Catalog ----
    if (pathname === '/teams') return json(route, 200, TEAMS)
    if (pathname === '/players') return json(route, 200, PLAYERS)
    if (pathname === '/games') return json(route, 200, GAMES)
    if (pathname === `/games/${GAME.id}`) return json(route, 200, GAME)
    if (pathname === `/games/${GAME.id}/prop-lines`) return json(route, 200, GAME_PROP_LINES)
    if (pathname === `/games/${GAME.id}/markets`) return json(route, 200, GAME_MARKETS)

    // Unknown game id → 404 so the UI shows its not-found state.
    if (/^\/games\/\d+/.test(pathname)) return json(route, 404, { detail: 'Game not found' })

    return json(route, 404, { detail: `unmocked ${method} ${pathname}` })
  })

  return { state, placedCount: () => placed }
}
