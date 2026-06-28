import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, getMlbGamePropLines, listMlbTeams } from '../api'
import type { MLBGamePropLinesBundle, MLBTeamRead } from '../api/types'
import { formatGameDate, formatTipOrGameStatusLabel } from '../components/browse/format'
import { MLBPropBoard } from '../components/mlb/MLBPropBoard'
import { gameAcceptsPreGameWagers } from '../lib/gameWagerGate'
import { mlbTeamLogoUrl } from '../lib/mlbMedia'

function parseId(raw: string | undefined): number | null {
  if (!raw) return null
  const n = Number.parseInt(raw, 10)
  return Number.isFinite(n) && n > 0 ? n : null
}

type LoadedState =
  | { kind: 'loading' }
  | { kind: 'ok'; propLines: MLBGamePropLinesBundle; teams: MLBTeamRead[] }
  | { kind: 'error'; message: string }

export function MLBGameDetailPage() {
  const { gameId: gameIdParam } = useParams()
  const id = parseId(gameIdParam)

  const [state, setState] = useState<LoadedState>({ kind: 'loading' })

  useEffect(() => {
    if (id == null) return
    let cancelled = false
    ;(async () => {
      try {
        const [propLines, teams] = await Promise.all([
          getMlbGamePropLines(id),
          listMlbTeams({ limit: 500 }),
        ])
        if (!cancelled) setState({ kind: 'ok', propLines, teams })
      } catch (e) {
        if (!cancelled) {
          const message =
            e instanceof ApiError && e.status === 404
              ? 'Game not found'
              : e instanceof ApiError
                ? e.message
                : 'MLB data currently unavailable'
          setState({ kind: 'error', message })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [id])

  if (id == null) {
    return (
      <div className="page page--browse">
        <section className="card">
          <h1 className="page-title">MLB Game</h1>
          <p className="status-err">Invalid game id in URL.</p>
          <p>
            <Link to="/mlb" className="inline-link">
              Back to MLB
            </Link>
          </p>
        </section>
      </div>
    )
  }

  if (state.kind === 'loading') {
    return (
      <div className="page page--browse page--game-detail">
        <p className="muted">Loading game…</p>
      </div>
    )
  }

  if (state.kind === 'error') {
    return (
      <div className="page page--browse">
        <section className="card">
          <h1 className="page-title">MLB Game</h1>
          <p className="status-err">{state.message}</p>
          <p>
            <Link to="/mlb" className="inline-link">
              Back to MLB
            </Link>
          </p>
        </section>
      </div>
    )
  }

  const { propLines, teams } = state
  const { game } = propLines
  const teamMap = new Map(teams.map((t) => [t.id, t]))
  const away = teamMap.get(game.away_team_id)?.name ?? `Team #${game.away_team_id}`
  const home = teamMap.get(game.home_team_id)?.name ?? `Team #${game.home_team_id}`
  const awayLogo = mlbTeamLogoUrl(teamMap.get(game.away_team_id)?.mlb_team_id)
  const homeLogo = mlbTeamLogoUrl(teamMap.get(game.home_team_id)?.mlb_team_id)
  const timeLabel = formatTipOrGameStatusLabel(game.game_time_utc, game.status)
  const slipHeader = `${away} @ ${home} · ${formatGameDate(game.game_date)}${timeLabel ? ` · ${timeLabel}` : ''}`
  const wageringLocked = !gameAcceptsPreGameWagers({ sport: 'MLB', status: game.status })

  return (
    <div className="page page--browse page--game-detail">
      <p className="game-detail__crumb">
        <Link to="/mlb" className="inline-link">
          ← MLB
        </Link>
      </p>

      <section className="card game-detail__hero">
        <p className="game-detail__eyebrow muted">
          {formatGameDate(game.game_date)} · {game.status}
        </p>
        <h1 className="game-detail__title">
          {awayLogo && (
            <img
              className="game-detail__team-logo"
              src={awayLogo}
              alt=""
              loading="lazy"
              decoding="async"
            />
          )}
          <span className="game-detail__away">{away}</span>
          <span className="game-detail__at muted"> @ </span>
          {homeLogo && (
            <img
              className="game-detail__team-logo"
              src={homeLogo}
              alt=""
              loading="lazy"
              decoding="async"
            />
          )}
          <span className="game-detail__home">{home}</span>
        </h1>
      </section>

      <MLBPropBoard bundle={propLines} slipGameHeader={slipHeader} wageringLocked={wageringLocked} />
    </div>
  )
}
