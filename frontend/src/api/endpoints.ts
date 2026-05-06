import { apiRequest } from './client'
import type {
  AccountRead,
  GameMarketsRead,
  GamePropLinesBundle,
  GameRead,
  HealthResponse,
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

export function getAccount(accountId: number) {
  return apiRequest<AccountRead>(`/accounts/${accountId}`)
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
