import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError, listPlayerStats, listPlayers, listTeams } from '../../api'
import type { PlayerGameStatRead, PlayerRead, TeamRead } from '../../api/types'
import { formatGameDate, formatStat } from './format'
import { LegPickerForm } from './LegPickerForm'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ok'; players: PlayerRead[]; teams: TeamRead[] }
  | { kind: 'error'; message: string }

function teamNameMap(teams: TeamRead[]): Map<number, string> {
  return new Map(teams.map((t) => [t.id, t.name]))
}

export function PlayersBrowse() {
  const [searchParams, setSearchParams] = useSearchParams()
  const gamePrefRaw = searchParams.get('game')
  const preferredGameId =
    gamePrefRaw != null && gamePrefRaw !== ''
      ? Number.parseInt(gamePrefRaw, 10)
      : null
  const preferredGameValid =
    preferredGameId != null && Number.isFinite(preferredGameId) && preferredGameId > 0

  const playerRaw = searchParams.get('player')
  const selectedPlayerId =
    playerRaw != null && playerRaw !== '' ? Number.parseInt(playerRaw, 10) : null
  const selectedPlayerValid =
    selectedPlayerId != null && Number.isFinite(selectedPlayerId) && selectedPlayerId > 0

  const [query, setQuery] = useState('')
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  type StatsLoad =
    | { kind: 'idle' }
    | { kind: 'loading' }
    | { kind: 'ok'; stats: PlayerGameStatRead[] }
    | { kind: 'error'; message: string }

  const [statsState, setStatsState] = useState<StatsLoad>({ kind: 'idle' })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [players, teams] = await Promise.all([listPlayers({ limit: 500 }), listTeams({ limit: 500 })])
        if (!cancelled) setState({ kind: 'ok', players, teams })
      } catch (e) {
        if (!cancelled) {
          setState({
            kind: 'error',
            message: e instanceof ApiError ? e.message : 'Failed to load players',
          })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedPlayerValid || selectedPlayerId == null) return

    let cancelled = false
    ;(async () => {
      setStatsState({ kind: 'loading' })
      try {
        const stats = await listPlayerStats(selectedPlayerId, { limit: 30 })
        if (!cancelled) setStatsState({ kind: 'ok', stats })
      } catch (e) {
        if (!cancelled) {
          setStatsState({
            kind: 'error',
            message: e instanceof ApiError ? e.message : 'Failed to load stats',
          })
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [selectedPlayerId, selectedPlayerValid])

  const names = useMemo(() => {
    if (state.kind !== 'ok') return new Map<number, string>()
    return teamNameMap(state.teams)
  }, [state])

  const filteredPlayers = useMemo(() => {
    if (state.kind !== 'ok') return []
    const q = query.trim().toLowerCase()
    if (!q) return state.players
    return state.players.filter((p) => p.full_name.toLowerCase().includes(q))
  }, [state, query])

  const selectPlayer = useCallback(
    (id: number | null) => {
      if (id == null) setStatsState({ kind: 'idle' })
      const next = new URLSearchParams(searchParams)
      if (id == null) next.delete('player')
      else next.set('player', String(id))
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const selectedPlayer =
    state.kind === 'ok' && selectedPlayerValid && selectedPlayerId != null
      ? state.players.find((p) => p.id === selectedPlayerId)
      : undefined

  if (state.kind === 'loading') {
    return (
      <section className="browse-panel card" aria-busy="true">
        <h2 className="browse-panel__title">Players</h2>
        <p className="muted browse-panel__status">Loading players…</p>
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="browse-panel card">
        <h2 className="browse-panel__title">Players</h2>
        <p className="status-err">{state.message}</p>
      </section>
    )
  }

  return (
    <section className="browse-panel card browse-panel--players">
      <h2 className="browse-panel__title">Players</h2>

      <label className="browse-search">
        <span className="visually-hidden">Search players</span>
        <input
          type="search"
          className="browse-search__input"
          placeholder="Search by name…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoComplete="off"
        />
      </label>

      {preferredGameValid && (
        <p className="browse-panel__hint muted">
          Game filter active (from Games tab). Props will prefer game #{preferredGameId} when available.
        </p>
      )}

      <div className="players-split">
        <div className="players-list">
          <ul className="players-list__ul" role="list">
            {filteredPlayers.length === 0 ? (
              <li className="muted">No players match.</li>
            ) : (
              filteredPlayers.map((p) => {
                const active = selectedPlayerValid && selectedPlayerId === p.id
                const team = names.get(p.team_id) ?? `#${p.team_id}`
                return (
                  <li key={p.id} className={active ? 'players-list__item players-list__item--active' : 'players-list__item'}>
                    <button type="button" className="players-list__btn" onClick={() => selectPlayer(p.id)}>
                      <span className="players-list__name">{p.full_name}</span>
                      <span className="players-list__team muted">{team}</span>
                    </button>
                  </li>
                )
              })
            )}
          </ul>
        </div>

        <div className="players-detail">
          {!selectedPlayerValid && <p className="muted players-detail__empty">Select a player to see game logs and add props.</p>}

          {selectedPlayerValid && selectedPlayer && (
            <>
              <div className="players-detail__header">
                <h3 className="players-detail__name">{selectedPlayer.full_name}</h3>
                <p className="players-detail__meta muted">{names.get(selectedPlayer.team_id) ?? 'Team unknown'}</p>
                <button type="button" className="btn-text players-detail__clear" onClick={() => selectPlayer(null)}>
                  Clear selection
                </button>
              </div>

              {statsState.kind === 'loading' && <p className="muted">Loading stats…</p>}
              {statsState.kind === 'error' && <p className="status-err">{statsState.message}</p>}

              {statsState.kind === 'ok' && (
                <>
                  <div className="browse-table-wrap browse-table-wrap--stats">
                    <table className="browse-table browse-table--compact">
                      <thead>
                        <tr>
                          <th scope="col">Date</th>
                          <th scope="col">PTS</th>
                          <th scope="col">REB</th>
                          <th scope="col">AST</th>
                          <th scope="col">MIN</th>
                        </tr>
                      </thead>
                      <tbody>
                        {statsState.stats.length === 0 ? (
                          <tr>
                            <td colSpan={5} className="muted">
                              No stat rows for this player.
                            </td>
                          </tr>
                        ) : (
                          statsState.stats.map((s) => (
                            <tr key={s.id}>
                              <td>{formatGameDate(s.game_date)}</td>
                              <td>{formatStat(s.points, 0)}</td>
                              <td>{formatStat(s.rebounds, 0)}</td>
                              <td>{formatStat(s.assists, 0)}</td>
                              <td>{formatStat(s.minutes)}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>

                  <LegPickerForm
                    key={`${selectedPlayer.id}-${searchParams.get('game') ?? ''}`}
                    playerId={selectedPlayer.id}
                    playerName={selectedPlayer.full_name}
                    teamName={names.get(selectedPlayer.team_id) ?? `Team ${selectedPlayer.team_id}`}
                    stats={statsState.stats}
                    preferredGameId={
                      preferredGameValid && preferredGameId != null ? preferredGameId : null
                    }
                  />
                </>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  )
}
