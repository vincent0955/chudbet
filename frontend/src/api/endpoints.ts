import { apiRequest } from './client'
import type {
  AccountRead,
  AuthLoginBody,
  AuthMeRead,
  AuthSignupBody,
  DepositBody,
  DepositResult,
  GameMarketsRead,
  GamePropLinesBundle,
  GameRead,
  HealthResponse,
  MLBGamePropLinesBundle,
  MLBGameRead,
  MLBPlayerRead,
  MLBTeamRead,
  ParlayCreate,
  ParlayRead,
  PlayerGameStatRead,
  PlayerRead,
  TeamRead,
  WagerDetailResponse,
  WagerPlaceBody,
  WagerRead,
} from './types'

function query(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) sp.set(k, String(v))
  }
  const q = sp.toString()
  return q ? `?${q}` : ''
}

export function getHealth() {
  return apiRequest<HealthResponse>('/health')
}

export function getAuthMe() {
  return apiRequest<AuthMeRead>('/auth/me')
}

export function login(body: AuthLoginBody) {
  return apiRequest<AuthMeRead>('/auth/login', { method: 'POST', body: JSON.stringify(body) })
}

export function signup(body: AuthSignupBody) {
  return apiRequest<AuthMeRead>('/auth/signup', { method: 'POST', body: JSON.stringify(body) })
}

export function loginGuest() {
  return apiRequest<AuthMeRead>('/auth/guest', { method: 'POST' })
}

export function logout() {
  return apiRequest<null>('/auth/logout', { method: 'POST' })
}

export function getAccount(accountId: number) {
  return apiRequest<AccountRead>(`/accounts/${accountId}`)
}

export function deposit(accountId: number, body: DepositBody) {
  return apiRequest<DepositResult>(`/accounts/${accountId}/deposit`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function placeWager(accountId: number, body: WagerPlaceBody) {
  return apiRequest<WagerDetailResponse>(`/accounts/${accountId}/wagers`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function listWagers(accountId: number, options?: { limit?: number }) {
  return apiRequest<WagerRead[]>(`/accounts/${accountId}/wagers${query({ limit: options?.limit })}`)
}

export function getWagerDetail(accountId: number, wagerId: number) {
  return apiRequest<WagerDetailResponse>(`/accounts/${accountId}/wagers/${wagerId}`)
}

export function listTeams(options?: { limit?: number; offset?: number }) {
  return apiRequest<TeamRead[]>(`/teams${query({ limit: options?.limit, offset: options?.offset })}`)
}

export function listPlayers(options?: { limit?: number; offset?: number }) {
  return apiRequest<PlayerRead[]>(`/players${query({ limit: options?.limit, offset: options?.offset })}`)
}

export function listGames(options?: { limit?: number; offset?: number }) {
  return apiRequest<GameRead[]>(`/games${query({ limit: options?.limit, offset: options?.offset })}`)
}

export function getGame(gameId: number) {
  return apiRequest<GameRead>(`/games/${gameId}`)
}

export function getGamePropLines(gameId: number) {
  return apiRequest<GamePropLinesBundle>(`/games/${gameId}/prop-lines`)
}

export function getGameMarkets(gameId: number) {
  return apiRequest<GameMarketsRead>(`/games/${gameId}/markets`)
}

// --- MLB ---

export function listMlbTeams(options?: { limit?: number; offset?: number }) {
  return apiRequest<MLBTeamRead[]>(`/mlb/teams${query({ limit: options?.limit, offset: options?.offset })}`)
}

export function listMlbPlayers(options?: { limit?: number; offset?: number }) {
  return apiRequest<MLBPlayerRead[]>(
    `/mlb/players${query({ limit: options?.limit, offset: options?.offset })}`,
  )
}

export function listMlbGames(options?: { limit?: number; offset?: number }) {
  return apiRequest<MLBGameRead[]>(`/mlb/games${query({ limit: options?.limit, offset: options?.offset })}`)
}

export function getMlbGameMarkets(gameId: number) {
  return apiRequest<GameMarketsRead>(`/mlb/games/${gameId}/markets`)
}

export function getMlbGamePropLines(gameId: number) {
  return apiRequest<MLBGamePropLinesBundle>(`/mlb/games/${gameId}/prop-lines`)
}

export function listPlayerStats(playerId: number, options?: { limit?: number; offset?: number }) {
  return apiRequest<PlayerGameStatRead[]>(
    `/players/${playerId}/stats${query({ limit: options?.limit, offset: options?.offset })}`,
  )
}

export function getParlay(parlayId: number) {
  return apiRequest<ParlayRead>(`/parlays/${parlayId}`)
}

export function createParlay(body: ParlayCreate) {
  return apiRequest<ParlayRead>('/parlays', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
