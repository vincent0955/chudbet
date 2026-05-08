import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, getGamePropLines, listTeams } from '../api'
import type { GamePropLinesBundle, TeamRead } from '../api/types'
import { formatGameDate, formatTipOrGameStatusLabel } from '../components/browse/format'
import { nbaTeamLogoUrl } from '../lib/nbaMedia'
import { GamePropBoard } from '../components/game/GamePropBoard'

function parseId(raw: string | undefined): number | null {
  if (!raw) return null
  const n = Number.parseInt(raw, 10)
  return Number.isFinite(n) && n > 0 ? n : null
}

function InvalidGameId() {
  return (
    <div className="page page--browse">
      <section className="card">
        <h1 className="page-title">Game</h1>
        <p className="status-err">Invalid game id in URL.</p>
        <p>
          <Link to="/" className="inline-link">
            Back home
          </Link>
        </p>
      </section>
    </div>
  )
}

function teamLabel(map: Map<number, string>, id: number): string {
  return map.get(id) ?? `Team #${id}`
}

function teamLogo(map: Map<number, TeamRead>, id: number): string | null {
  return nbaTeamLogoUrl(map.get(id)?.nba_team_id)
}

type LoadedState =
  | { kind: 'loading' }
  | {
      kind: 'ok'
      propLines: GamePropLinesBundle
      teams: TeamRead[]
    }
  | { kind: 'error'; message: string }

function GameDetailLoaded({ id }: { id: number }) {
  const [state, setState] = useState<LoadedState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [propLines, teams] = await Promise.all([
          getGamePropLines(id),
          listTeams({ limit: 500 }),
        ])
        if (!cancelled) {
          setState({
            kind: 'ok',
            propLines,
            teams,
          })
        }
      } catch (e) {
        if (!cancelled) {
          const message =
            e instanceof ApiError && e.status === 404
              ? 'Game not found'
              : e instanceof ApiError
                ? e.message
                : 'Failed to load game'
          setState({ kind: 'error', message })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [id])

  if (state.kind === 'loading') {
    return (
      <div className="page page--browse page--game-detail">
        <p className="muted">Loading game & props…</p>
      </div>
    )
  }

  if (state.kind === 'error') {
    return (
      <div className="page page--browse">
        <section className="card">
          <h1 className="page-title">Game</h1>
          <p className="status-err">{state.message}</p>
          <p>
            <Link to="/" className="inline-link">
              Back home
            </Link>
          </p>
        </section>
      </div>
    )
  }

  const { propLines, teams } = state
  const { game } = propLines
  const tmap = new Map(teams.map((t) => [t.id, t.name]))
  const teamsById = new Map(teams.map((t) => [t.id, t]))
  const away = teamLabel(tmap, game.away_team_id)
  const home = teamLabel(tmap, game.home_team_id)
  const awayLogo = teamLogo(teamsById, game.away_team_id)
  const homeLogo = teamLogo(teamsById, game.home_team_id)
  const slipParts = [`${away} @ ${home}`, formatGameDate(game.game_date)]
  const tail = formatTipOrGameStatusLabel(game.game_time_utc, game.status)
  if (tail) slipParts.push(tail)

  return (
    <div className="page page--browse page--game-detail">
      <p className="game-detail__crumb">
        <Link to="/" className="inline-link">
          ← Home
        </Link>
      </p>

      <section className="card game-detail__hero">
        <p className="game-detail__eyebrow muted">{formatGameDate(game.game_date)} · {game.status}</p>
        <h1 className="game-detail__title">
          {awayLogo && <img className="game-detail__team-logo" src={awayLogo} alt="" loading="lazy" decoding="async" />}
          <span className="game-detail__away">{away}</span>
          <span className="game-detail__at muted"> @ </span>
          {homeLogo && <img className="game-detail__team-logo" src={homeLogo} alt="" loading="lazy" decoding="async" />}
          <span className="game-detail__home">{home}</span>
        </h1>
      </section>

      <GamePropBoard bundle={propLines} slipGameHeader={slipParts.join(' · ')} />
    </div>
  )
}

export function GameDetailPage() {
  const { gameId } = useParams<{ gameId: string }>()
  const id = parseId(gameId)

  if (!id) {
    return <InvalidGameId />
  }

  return <GameDetailLoaded key={gameId} id={id} />
}
