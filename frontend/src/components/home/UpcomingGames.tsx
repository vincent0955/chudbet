import { useEffect, useMemo, useState, type MouseEvent } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getGameMarkets, getHealth, listGames, listTeams } from '../../api'
import type { GameLegIn, GameMarketsRead, GameRead, TeamRead } from '../../api/types'
import { useBetSlip } from '../../context/BetSlipContext'
import { parseAmericanOddsString } from '../../utils/parlayOdds'
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

function isLiveOrClosedStatus(statusRaw: string | null | undefined): boolean {
  const s = String(statusRaw ?? '').trim().toUpperCase()
  if (!s) return false
  if (s.includes('FINAL') || s.includes('POSTPONED') || s.includes('CANCELLED')) return true
  if (s.includes('HALFTIME') || s.includes('END OF')) return true
  if (/^Q[1-4]\b/.test(s) || /^OT\b/.test(s)) return true
  if (/^\d{1,2}:\d{2}\b/.test(s) && !s.includes('AM') && !s.includes('PM') && !s.includes('ET')) return true
  return false
}

function isBettableUpcomingGame(game: GameRead, todayIso: string): boolean {
  if (game.game_date > todayIso) return true
  if (game.game_date < todayIso) return false
  return !isLiveOrClosedStatus(game.status)
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

function GameOddsRow({
  game,
  teamLabel,
  gameHeader,
  markets,
  side,
}: {
  game: GameRead
  teamLabel: string
  gameHeader: string
  markets: MarketTriple
  side: 'away' | 'home'
}) {
  const { addLeg, hasLeg, removeLegByLeg } = useBetSlip()
  const spreadLine = Number.parseFloat(markets.spread.line)
  const spreadOdds = parseAmericanOddsString(markets.spread.odds)
  const moneylineOdds = parseAmericanOddsString(markets.ml)
  const totalValue = Number.parseFloat(markets.total.sidePoints.replace(/[^\d.]/g, ''))
  const totalOdds = parseAmericanOddsString(markets.total.odds)
  const totalOver = markets.total.sidePoints.trim().toUpperCase().startsWith('O')

  const spreadLeg: GameLegIn | null =
    Number.isFinite(spreadLine) && spreadOdds != null
      ? {
          game_id: game.id,
          market_type: 'spread',
          selection: side === 'home' ? 'home' : 'away',
          line: spreadLine,
          odds_american: spreadOdds,
        }
      : null
  const mlLeg: GameLegIn | null =
    moneylineOdds != null
      ? {
          game_id: game.id,
          market_type: 'moneyline',
          selection: side === 'home' ? 'home' : 'away',
          line: null,
          odds_american: moneylineOdds,
        }
      : null
  const totalLeg: GameLegIn | null =
    Number.isFinite(totalValue) && totalOdds != null
      ? {
          game_id: game.id,
          market_type: 'total',
          selection: totalOver ? 'over' : 'under',
          line: totalValue,
          odds_american: totalOdds,
        }
      : null

  const toggle = (leg: GameLegIn | null, label: string) => {
    if (!leg) return
    const wrapped = { kind: 'game' as const, leg }
    if (hasLeg(wrapped)) {
      removeLegByLeg(wrapped)
      return
    }
    addLeg(
      wrapped,
      {
        playerLine: teamLabel,
        propLine: label,
        gameSlipHeader: gameHeader,
      },
      leg.odds_american,
    )
  }

  const onPillClick =
    (leg: GameLegIn | null, label: string) => (e: MouseEvent<HTMLButtonElement>) => {
      e.preventDefault()
      e.stopPropagation()
      toggle(leg, label)
    }

  const spreadSelected = spreadLeg ? hasLeg({ kind: 'game', leg: spreadLeg }) : false
  const mlSelected = mlLeg ? hasLeg({ kind: 'game', leg: mlLeg }) : false
  const totalSelected = totalLeg ? hasLeg({ kind: 'game', leg: totalLeg }) : false

  return (
    <div className="upcoming-game-bar__line">
      <span className="upcoming-game-bar__team">{teamLabel}</span>
      <button
        type="button"
        className={`upcoming-game-bar__pill-btn${spreadSelected ? ' upcoming-game-bar__pill-btn--selected' : ''}`}
        onClick={onPillClick(spreadLeg, `Spread ${markets.spread.line}`)}
      >
        <StackedOddsPill top={markets.spread.line} bottom={markets.spread.odds} />
      </button>
      <button
        type="button"
        className={`upcoming-game-bar__pill-btn${mlSelected ? ' upcoming-game-bar__pill-btn--selected' : ''}`}
        onClick={onPillClick(mlLeg, 'Moneyline')}
      >
        <span className="upcoming-game-bar__pill upcoming-game-bar__pill--plain">{markets.ml}</span>
      </button>
      <button
        type="button"
        className={`upcoming-game-bar__pill-btn${totalSelected ? ' upcoming-game-bar__pill-btn--selected' : ''}`}
        onClick={onPillClick(totalLeg, `Total ${markets.total.sidePoints}`)}
      >
        <StackedOddsPill top={markets.total.sidePoints} bottom={markets.total.odds} />
      </button>
    </div>
  )
}

export function UpcomingGames() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [marketsByGameId, setMarketsByGameId] = useState<Record<number, { away: MarketTriple; home: MarketTriple }>>({})

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
    const filtered = state.games.filter((g) => isBettableUpcomingGame(g, today))
    filtered.sort((a, b) => {
      if (a.game_date !== b.game_date) return a.game_date < b.game_date ? -1 : 1
      return a.id - b.id
    })
    return filtered
  }, [state])

  useEffect(() => {
    if (state.kind !== 'ok') return
    const target = [...upcoming].slice(0, 60)
    let cancelled = false
    ;(async () => {
      const pairs = await Promise.all(
        target.map(async (g) => {
          try {
            const m: GameMarketsRead = await getGameMarkets(g.id)
            const mapped = {
              away: {
                spread: { line: `${m.spread.away_line >= 0 ? '+' : ''}${m.spread.away_line.toFixed(1)}`, odds: m.spread.away_american },
                ml: m.moneyline.away_american,
                total: { sidePoints: `O ${m.total.line.toFixed(1)}`, odds: m.total.over_american },
              },
              home: {
                spread: { line: `${m.spread.home_line >= 0 ? '+' : ''}${m.spread.home_line.toFixed(1)}`, odds: m.spread.home_american },
                ml: m.moneyline.home_american,
                total: { sidePoints: `U ${m.total.line.toFixed(1)}`, odds: m.total.under_american },
              },
            }
            return [g.id, mapped] as const
          } catch {
            return null
          }
        }),
      )
      if (cancelled) return
      const next: Record<number, { away: MarketTriple; home: MarketTriple }> = {}
      for (const p of pairs) {
        if (!p) continue
        next[p[0]] = p[1]
      }
      setMarketsByGameId(next)
    })()
    return () => {
      cancelled = true
    }
  }, [state, upcoming])

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
              const mkts = marketsByGameId[g.id] ?? placeholderMarkets(i)
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
                      <GameOddsRow
                        game={g}
                        teamLabel={away}
                        gameHeader={`${away} @ ${home} · ${formatGameDate(g.game_date)} · ${g.status}`}
                        markets={mkts.away}
                        side="away"
                      />
                      <GameOddsRow
                        game={g}
                        teamLabel={home}
                        gameHeader={`${away} @ ${home} · ${formatGameDate(g.game_date)} · ${g.status}`}
                        markets={mkts.home}
                        side="home"
                      />
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
