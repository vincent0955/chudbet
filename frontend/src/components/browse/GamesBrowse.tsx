import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError, listGames, listTeams } from '../../api'
import type { GameRead, TeamRead } from '../../api/types'
import { formatGameDate } from './format'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ok'; games: GameRead[]; teams: TeamRead[] }
  | { kind: 'error'; message: string }

function teamMap(teams: TeamRead[]): Map<number, string> {
  return new Map(teams.map((t) => [t.id, t.name]))
}

function matchupLabel(g: GameRead, names: Map<number, string>): string {
  const away = names.get(g.away_team_id) ?? `Team #${g.away_team_id}`
  const home = names.get(g.home_team_id) ?? `Team #${g.home_team_id}`
  return `${away} @ ${home}`
}

export function GamesBrowse() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedRaw = searchParams.get('game')
  const selectedGameId =
    selectedRaw != null && selectedRaw !== '' ? Number.parseInt(selectedRaw, 10) : null
  const selectedValid = selectedGameId != null && Number.isFinite(selectedGameId) && selectedGameId > 0

  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [games, teams] = await Promise.all([listGames({ limit: 500 }), listTeams({ limit: 500 })])
        if (!cancelled) setState({ kind: 'ok', games, teams })
      } catch (e) {
        if (!cancelled) {
          setState({
            kind: 'error',
            message: e instanceof ApiError ? e.message : 'Failed to load games',
          })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const names = useMemo(() => {
    if (state.kind !== 'ok') return new Map<number, string>()
    return teamMap(state.teams)
  }, [state])

  const toggleGame = useCallback(
    (gameId: number) => {
      const next = new URLSearchParams(searchParams)
      if (selectedValid && selectedGameId === gameId) {
        next.delete('game')
      } else {
        next.set('game', String(gameId))
      }
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams, selectedGameId, selectedValid],
  )

  const clearGame = useCallback(() => {
    const next = new URLSearchParams(searchParams)
    next.delete('game')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  if (state.kind === 'loading') {
    return (
      <section className="browse-panel card" aria-busy="true">
        <h2 className="browse-panel__title">Games</h2>
        <p className="muted browse-panel__status">Loading games…</p>
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="browse-panel card">
        <h2 className="browse-panel__title">Games</h2>
        <p className="status-err">{state.message}</p>
      </section>
    )
  }

  const { games } = state

  return (
    <section className="browse-panel card">
      <div className="browse-panel__header">
        <h2 className="browse-panel__title">Games</h2>
        {selectedValid && (
          <button type="button" className="btn-text" onClick={clearGame}>
            Clear selection
          </button>
        )}
      </div>
      <p className="browse-panel__hint muted">
        Select a matchup to pre-fill the game when you add a prop from the Players tab (if that player has a line for
        that game).
      </p>

      <div className="browse-table-wrap">
        <table className="browse-table">
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Matchup</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {games.length === 0 ? (
              <tr>
                <td colSpan={3} className="muted">
                  No games in the database yet.
                </td>
              </tr>
            ) : (
              games.map((g) => {
                const active = selectedValid && selectedGameId === g.id
                return (
                  <tr
                    key={g.id}
                    className={active ? 'browse-table__row browse-table__row--active' : 'browse-table__row'}
                  >
                    <td>{formatGameDate(g.game_date)}</td>
                    <td>
                      <button type="button" className="browse-table__link" onClick={() => toggleGame(g.id)}>
                        {matchupLabel(g, names)}
                      </button>
                    </td>
                    <td>
                      <span className="browse-table__pill">{g.status}</span>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
