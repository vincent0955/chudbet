export function nbaTeamLogoUrl(nbaTeamId: number | null | undefined): string | null {
  if (nbaTeamId == null || !Number.isFinite(nbaTeamId)) return null
  return `https://cdn.nba.com/logos/nba/${nbaTeamId}/global/L/logo.svg`
}

export function nbaPlayerHeadshotUrl(nbaPlayerId: number | null | undefined): string | null {
  if (nbaPlayerId == null || !Number.isFinite(nbaPlayerId)) return null
  return `https://cdn.nba.com/headshots/nba/latest/1040x760/${nbaPlayerId}.png`
}
