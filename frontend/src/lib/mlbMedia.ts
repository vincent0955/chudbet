export function mlbTeamLogoUrl(mlbTeamId: number | null | undefined): string | null {
  if (mlbTeamId == null || !Number.isFinite(mlbTeamId)) return null
  return `https://www.mlbstatic.com/team-logos/${mlbTeamId}.svg`
}

export function mlbPlayerHeadshotUrl(mlbPlayerId: number | null | undefined): string | null {
  if (mlbPlayerId == null || !Number.isFinite(mlbPlayerId)) return null
  return `https://midfield.mlbstatic.com/v1/people/${mlbPlayerId}/spots/120`
}
