import { useEffect, useMemo, useState, type MouseEvent } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, getMlbGameMarkets, getHealth, listMlbGames, listMlbTeams } from '../../api'
import type { GameLegIn, GameMarketsRead, MLBGameRead, MLBTeamRead } from '../../api/types'
import { useBetSlip } from '../../context/BetSlipContext'
import { mlbTeamLogoUrl } from '../../lib/mlbMedia'
import { gameAcceptsPreGameWagers } from '../../lib/gameWagerGate'
import { parseAmericanOddsString } from '../../utils/parlayOdds'
import { formatGameDate } from '../browse/format'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'ok'; games: MLBGameRead[]; teams: MLBTeamRead[] }
  | { kind: 'empty' }
  | { kind: 'error'; message: string }

function teamName(map: Map<number, MLBTeamRead>, id: number): string {
  return map.get(id)?.name ?? `Team #${id}`
}

function teamLogo(map: Map<number, MLBTeamRead>, id: number): string | null {
  return mlbTeamLogoUrl(map.get(id)?.mlb_team_id)
}

type SpreadParts = { line: string; odds: string }
type TotalParts = { sidePoints: string; odds: string }
type MarketTriple = { spread: SpreadParts; ml: string; total: TotalParts }

function StackedOddsPill({ top, bottom }: { top: string; bottom: string }) {
  return (
    <span className="upcoming-game-bar__pill upcoming-game-bar__pill--stack">
      <span className="upcoming-game-bar__pill-line">{top}</span>
      <span className="upcoming-game-bar__pill-odds">{bottom}</span>
    </span>
  )
}

function TeamLogoImg({ url }: { url: string | null; label: string }) {
  const [broken, setBroken] = useState(false)
  if (!url || broken) {
    return <span className="upcoming-game-bar__logo upcoming-game-bar__logo--placeholder" aria-hidden />
  }
  return (
    <img
      className="upcoming-game-bar__logo"
      src={url}
      alt=""
      loading="lazy"
      decoding="async"
      onError={() => setBroken(true)}
    />
  )
}

function GameOddsRow({
  game,
  teamLabel,
  teamLogoUrl,
  gameHeader,
  markets,
  side,
  showAt,
}: {
  game: MLBGameRead
  teamLabel: string
  teamLogoUrl: string | null
  gameHeader: string
  markets: MarketTriple
  side: 'away' | 'home'
  showAt?: boolean
}) {
  const { addLeg, hasLeg, removeLegByLeg } = useBetSlip()
  const spreadLine = Number.parseFloat(markets.spread.line)
  const spreadOdds = parseAmericanOddsString(markets.spread.odds) ?? -110
  const mlOdds = parseAmericanOddsString(markets.ml) ?? -110
  const totalLine = Number.parseFloat(markets.total.sidePoints.replace(/^[OU]\s*/, ''))
  const totalOdds = parseAmericanOddsString(markets.total.odds) ?? -110
  const wagerable = gameAcceptsPreGameWagers({ sport: 'MLB', status: game.status })

  const spreadLeg: GameLegIn = {
    game_id: game.id,
    market_type: 'spread',
    selection: side,
    line: spreadLine,
    odds_american: spreadOdds,
  }
  const mlLeg: GameLegIn = {
    game_id: game.id,
    market_type: 'moneyline',
    selection: side,
    odds_american: mlOdds,
  }
  const totalSelection = markets.total.sidePoints.startsWith('O') ? 'over' : 'under'
  const totalLeg: GameLegIn = {
    game_id: game.id,
    market_type: 'total',
    selection: totalSelection as 'over' | 'under',
    line: totalLine,
    odds_american: totalOdds,
  }

  const toggle = (e: MouseEvent, leg: GameLegIn, label: string) => {
    e.preventDefault()
    e.stopPropagation()
    if (!wagerable) return
    const key = { kind: 'game' as const, leg }
    if (hasLeg(key)) {
      removeLegByLeg(key)
      return
    }
    addLeg(key, { playerLine: teamLabel, propLine: label, gameSlipHeader: gameHeader }, leg.odds_american)
  }

  return (
    <div className="upcoming-game-bar__team-row">
      <div className="upcoming-game-bar__team">
        <TeamLogoImg url={teamLogoUrl} label={teamLabel} />
        <span className="upcoming-game-bar__team-name">
          {showAt ? `@ ${teamLabel}` : teamLabel}
        </span>
      </div>
      <div className="upcoming-game-bar__markets">
        <button
          type="button"
          className="upcoming-game-bar__market-btn"
          disabled={!wagerable}
          onClick={(e) => toggle(e, spreadLeg, `Run Line ${markets.spread.line} (${markets.spread.odds})`)}
        >
          <StackedOddsPill top={markets.spread.line} bottom={markets.spread.odds} />
        </button>
        <button
          type="button"
          className="upcoming-game-bar__market-btn"
          disabled={!wagerable}
          onClick={(e) => toggle(e, mlLeg, `ML ${markets.ml}`)}
        >
          <span className="upcoming-game-bar__pill">{markets.ml}</span>
        </button>
        <button
          type="button"
          className="upcoming-game-bar__market-btn"
          disabled={!wagerable}
          onClick={(e) => toggle(e, totalLeg, `${markets.total.sidePoints} (${markets.total.odds})`)}
        >
          <StackedOddsPill top={markets.total.sidePoints} bottom={markets.total.odds} />
        </button>
      </div>
    </div>
  )
}

export function MLBUpcomingGames() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [marketsByGameId, setMarketsByGameId] = useState<Record<number, { away: MarketTriple; home: MarketTriple }>>({})

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        await getHealth()
        const [games, teams] = await Promise.all([
          listMlbGames({ limit: 5000, offset: 0 }),
          listMlbTeams({ limit: 500, offset: 0 }),
        ])
        if (cancelled) return
        if (games.length === 0 && teams.length === 0) {
          setState({ kind: 'empty' })
          return
        }
        setState({ kind: 'ok', games, teams })
      } catch (e) {
        if (!cancelled) {
          setState({
            kind: 'error',
            message: e instanceof ApiError ? e.message : 'MLB data currently unavailable',
          })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const teamsMap = useMemo(() => {
    if (state.kind !== 'ok') return new Map<number, MLBTeamRead>()
    return new Map(state.teams.map((t) => [t.id, t]))
  }, [state])

  const upcoming = useMemo(() => {
    if (state.kind !== 'ok') return []
    return state.games.filter((g) => gameAcceptsPreGameWagers({ sport: 'MLB', status: g.status }))
  }, [state])

  useEffect(() => {
    if (state.kind !== 'ok') return
    const target = [...upcoming].slice(0, 60)
    let cancelled = false
    ;(async () => {
      const pairs = await Promise.all(
        target.map(async (g) => {
          try {
            const m: GameMarketsRead = await getMlbGameMarkets(g.id)
            const mapped = {
              away: {
                spread: {
                  line: `${m.spread.away_line >= 0 ? '+' : ''}${m.spread.away_line.toFixed(1)}`,
                  odds: m.spread.away_american,
                },
                ml: m.moneyline.away_american,
                total: { sidePoints: `O ${m.total.line.toFixed(1)}`, odds: m.total.over_american },
              },
              home: {
                spread: {
                  line: `${m.spread.home_line >= 0 ? '+' : ''}${m.spread.home_line.toFixed(1)}`,
                  odds: m.spread.home_american,
                },
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
        <h2 className="upcoming-games__title">Upcoming MLB games</h2>
        <p className="muted">Loading schedule…</p>
      </section>
    )
  }

  if (state.kind === 'error') {
    return (
      <section className="upcoming-games card">
        <h2 className="upcoming-games__title">Upcoming MLB games</h2>
        <p className="status-err">MLB data currently unavailable</p>
      </section>
    )
  }

  if (state.kind === 'empty') {
    return (
      <section className="upcoming-games card">
        <h2 className="upcoming-games__title">Upcoming MLB games</h2>
        <p className="muted upcoming-games__empty">No MLB content available</p>
      </section>
    )
  }

  return (
    <section className="upcoming-games card">
      <h2 className="upcoming-games__title">Upcoming MLB games</h2>

      {upcoming.length === 0 ? (
        <p className="muted upcoming-games__empty">No MLB content available</p>
      ) : (
        <div className="upcoming-games__schedule">
          <div className="upcoming-games__market-head-row">
            <div className="upcoming-games__market-accent-spacer" aria-hidden />
            <div className="upcoming-games__market-head">
              <span className="upcoming-games__market-corner" aria-hidden />
              <span className="upcoming-games__market-th">Run Line</span>
              <span className="upcoming-games__market-th">ML</span>
              <span className="upcoming-games__market-th">Total</span>
            </div>
          </div>
          <ul className="upcoming-games__list">
            {upcoming.map((g) => {
              const away = teamName(teamsMap, g.away_team_id)
              const home = teamName(teamsMap, g.home_team_id)
              const awayLogo = teamLogo(teamsMap, g.away_team_id)
              const homeLogo = teamLogo(teamsMap, g.home_team_id)
              const mkts = marketsByGameId[g.id]
              if (!mkts) return null
              return (
                <li key={g.id}>
                  <Link className="upcoming-game-bar" to={`/mlb/games/${g.id}`}>
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
                        teamLogoUrl={awayLogo}
                        gameHeader={`${away} @ ${home} · ${formatGameDate(g.game_date)} · ${g.status}`}
                        markets={mkts.away}
                        side="away"
                      />
                      <GameOddsRow
                        game={g}
                        teamLabel={home}
                        teamLogoUrl={homeLogo}
                        gameHeader={`${away} @ ${home} · ${formatGameDate(g.game_date)} · ${g.status}`}
                        markets={mkts.home}
                        side="home"
                        showAt
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
