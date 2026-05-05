import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getHealth, listGames, listTeams } from '../../api'
import type { GameRead, TeamRead } from '../../api/types'
import { formatGameDate } from '../browse/format'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ok'; games: GameRead[]; teams: TeamRead[] }
  | { kind: 'error'; message: string }

function teamName(map: Map<number, string>, id: number): string {
  return map.get(id) ?? `Team #${id}`
}

function localTodayIso(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

type SpreadParts = { line: string; odds: string }
type TotalParts = { sidePoints: string; odds: string }

type MarketTriple = { spread: SpreadParts; ml: string; total: TotalParts }

/** Placeholder spread / ML / total until real lines exist. */
function placeholderMarkets(index: number): { away: MarketTriple; home: MarketTriple } {
  const presets: { away: MarketTriple; home: MarketTriple }[] = [
    {
      away: {
        spread: { line: '+7.5', odds: '-110' },
        ml: '+155',
        total: { sidePoints: 'O 224.5', odds: '-108' },
      },
      home: {
        spread: { line: '-7.5', odds: '-112' },
        ml: '-185',
        total: { sidePoints: 'U 224.5', odds: '-112' },
      },
    },
    {
      away: {
        spread: { line: '+3.5', odds: '-108' },
        ml: '+132',
        total: { sidePoints: 'O 218.0', odds: '-110' },
      },
      home: {
        spread: { line: '-3.5', odds: '-118' },
        ml: '-158',
        total: { sidePoints: 'U 218.0', odds: '-112' },
      },
    },
    {
      away: {
        spread: { line: '+1.5', odds: '-115' },
        ml: '+108',
        total: { sidePoints: 'O 231.5', odds: '-105' },
      },
      home: {
        spread: { line: '-1.5', odds: '-112' },
        ml: '-128',
        total: { sidePoints: 'U 231.5', odds: '-118' },
      },
    },
    {
      away: {
        spread: { line: '+11.5', odds: '-105' },
        ml: '+520',
        total: { sidePoints: 'O 212.5', odds: '-112' },
      },
      home: {
        spread: { line: '-11.5', odds: '-118' },
        ml: '-750',
        total: { sidePoints: 'U 212.5', odds: '-108' },
      },
    },
    {
      away: {
        spread: { line: '+5.0', odds: '-110' },
        ml: '+142',
        total: { sidePoints: 'O 226.0', odds: '-108' },
      },
      home: {
        spread: { line: '-5.0', odds: '-112' },
        ml: '-168',
        total: { sidePoints: 'U 226.0', odds: '-112' },
      },
    },
  ]
  return presets[index % presets.length]
}

function StackedOddsPill({ top, bottom }: { top: string; bottom: string }) {
  return (
    <span className="upcoming-game-bar__pill upcoming-game-bar__pill--stack">
      <span className="upcoming-game-bar__pill-line">{top}</span>
      <span className="upcoming-game-bar__pill-odds">{bottom}</span>
    </span>
  )
}

function GameOddsRow({ teamLabel, markets }: { teamLabel: string; markets: MarketTriple }) {
  return (
    <div className="upcoming-game-bar__line">
      <span className="upcoming-game-bar__team">{teamLabel}</span>
      <StackedOddsPill top={markets.spread.line} bottom={markets.spread.odds} />
      <span className="upcoming-game-bar__pill upcoming-game-bar__pill--plain">{markets.ml}</span>
      <StackedOddsPill top={markets.total.sidePoints} bottom={markets.total.odds} />
    </div>
  )
}

export function UpcomingGames() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        await getHealth()
        const [games, teams] = await Promise.all([
          listGames({ limit: 5000, offset: 0 }),
          listTeams({ limit: 500, offset: 0 }),
        ])
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

  const teamsMap = useMemo(() => {
    if (state.kind !== 'ok') return new Map<number, string>()
    return new Map(state.teams.map((t) => [t.id, t.name]))
  }, [state])

  const upcoming = useMemo(() => {
    if (state.kind !== 'ok') return []
    const today = localTodayIso()
    const filtered = state.games.filter((g) => g.game_date >= today)
    filtered.sort((a, b) => {
      if (a.game_date !== b.game_date) return a.game_date < b.game_date ? -1 : 1
      return a.id - b.id
    })
    return filtered
  }, [state])

  if (state.kind === 'loading') {
    return (
      <section className="upcoming-games card" aria-busy="true">
        <h2 className="upcoming-games__title">Upcoming games</h2>
        <p className="muted">Loading schedule…</p>
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="upcoming-games card">
        <h2 className="upcoming-games__title">Upcoming games</h2>
        <p className="status-err">{state.message}</p>
      </section>
    )
  }

  return (
    <section className="upcoming-games card">
      <h2 className="upcoming-games__title">Upcoming games</h2>
      <p className="upcoming-games__subtitle muted">
        Spread, moneyline, and total are placeholders. Open a game to build props (coming next).
      </p>

      {upcoming.length === 0 ? (
        <p className="muted upcoming-games__empty">No upcoming games in the feed (try refreshing ingestion).</p>
      ) : (
        <div className="upcoming-games__schedule">
          <div className="upcoming-games__market-head-row">
            <div className="upcoming-games__market-accent-spacer" aria-hidden />
            <div className="upcoming-games__market-head">
              <span className="upcoming-games__market-corner" aria-hidden />
              <span className="upcoming-games__market-th">Spread</span>
              <span className="upcoming-games__market-th">ML</span>
              <span className="upcoming-games__market-th">Total</span>
            </div>
          </div>
          <ul className="upcoming-games__list">
            {upcoming.map((g, i) => {
              const away = teamName(teamsMap, g.away_team_id)
              const home = teamName(teamsMap, g.home_team_id)
              const mkts = placeholderMarkets(i)
              return (
                <li key={g.id}>
                  <Link className="upcoming-game-bar" to={`/games/${g.id}`}>
                    <div className="upcoming-game-bar__accent" aria-hidden />
                    <div className="upcoming-game-bar__main">
                      <div className="upcoming-game-bar__meta-row">
                        <div className="upcoming-game-bar__meta-left">
                          <span className="upcoming-game-bar__meta-date">{formatGameDate(g.game_date)}</span>
                          <span className="upcoming-game-bar__meta-sep">–</span>
                          <span className="upcoming-game-bar__status">{g.status}</span>
                        </div>
                      </div>
                      <GameOddsRow teamLabel={away} markets={mkts.away} />
                      <GameOddsRow teamLabel={home} markets={mkts.home} />
                    </div>
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </section>
  )
}
