import { useId, useMemo, useState, type FormEvent } from 'react'
import type { LegIn, PlayerGameStatRead, StatType } from '../../api/types'
import { useBetSlip } from '../../context/BetSlipContext'
import { formatGameDate, formatStat } from './format'

const STAT_TYPES: StatType[] = ['PTS', 'REB', 'AST']

type Props = {
  playerId: number
  playerName: string
  teamName: string
  stats: PlayerGameStatRead[]
  /** From Games tab: optional game to prefer in the dropdown */
  preferredGameId: number | null
}

function statColumn(stat: StatType): keyof Pick<PlayerGameStatRead, 'points' | 'rebounds' | 'assists'> {
  if (stat === 'PTS') return 'points'
  if (stat === 'REB') return 'rebounds'
  return 'assists'
}

function directionLabel(d: LegIn['direction']): string {
  return d === 'OVER' ? 'Over' : 'Under'
}

export function LegPickerForm({ playerId, playerName, teamName, stats, preferredGameId }: Props) {
  const formId = useId()
  const { addLeg } = useBetSlip()

  const [statType, setStatType] = useState<StatType>('PTS')
  const [direction, setDirection] = useState<LegIn['direction']>('OVER')
  const [line, setLine] = useState('20.5')
  /** `undefined` = follow preferred URL / empty default; otherwise user-picked value including "" for any game */
  const [gameIdUser, setGameIdUser] = useState<string | undefined>(undefined)
  const [submitErr, setSubmitErr] = useState<string | null>(null)

  const gameOptions = useMemo(() => {
    const rows = stats.map((s) => ({ game_id: s.game_id, game_date: s.game_date }))
    const seen = new Set<number>()
    const uniq: { game_id: number; game_date: string }[] = []
    for (const r of rows) {
      if (seen.has(r.game_id)) continue
      seen.add(r.game_id)
      uniq.push(r)
    }
    return uniq.sort((a, b) => (a.game_date < b.game_date ? 1 : -1))
  }, [stats])

  const preferredMatches =
    preferredGameId != null && gameOptions.some((o) => o.game_id === preferredGameId)
  const gameIdFromPreferred = preferredMatches ? String(preferredGameId) : ''
  const gameSelectValue = gameIdUser !== undefined ? gameIdUser : gameIdFromPreferred

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    setSubmitErr(null)

    const parsed = Number.parseFloat(line)
    if (!Number.isFinite(parsed) || parsed < -5 || parsed >= 200) {
      setSubmitErr('Line must be a number between -5 and 200 (exclusive of 200).')
      return
    }

    const gid = gameSelectValue === '' ? null : Number.parseInt(gameSelectValue, 10)
    if (gid != null && !Number.isFinite(gid)) {
      setSubmitErr('Invalid game.')
      return
    }

    const leg: LegIn = {
      player_id: playerId,
      game_id: gid,
      stat_type: statType,
      line: parsed,
      direction,
    }

    const col = statColumn(statType)
    const sample = stats.find((s) => (gid == null ? true : s.game_id === gid))
    const refVal = sample?.[col]
    const statHint =
      refVal != null
        ? `Last in row: ${formatStat(typeof refVal === 'number' ? refVal : Number(refVal))} ${statType}`
        : undefined

    const primary = `${playerName} · ${statType} ${directionLabel(direction)} ${parsed}`
    const gameRow = gid != null ? gameOptions.find((o) => o.game_id === gid) : undefined
    const secondary = [
      teamName,
      gameRow ? formatGameDate(gameRow.game_date) : 'No specific game',
      statHint,
    ]
      .filter(Boolean)
      .join(' · ')

    addLeg(leg, { primary, secondary })
  }

  return (
    <form className="leg-form card card--inset" onSubmit={handleSubmit} aria-labelledby={`${formId}-title`}>
      <h3 className="leg-form__title" id={`${formId}-title`}>
        Add prop
      </h3>
      <p className="leg-form__player muted">
        {playerName} · {teamName}
      </p>

      <div className="leg-form__grid">
        <label className="leg-form__field">
          <span className="leg-form__label">Game (optional)</span>
          <select
            className="leg-form__input"
            value={gameSelectValue}
            onChange={(e) => setGameIdUser(e.target.value)}
          >
            <option value="">Any / not tied to one game</option>
            {gameOptions.map((o) => (
              <option key={o.game_id} value={String(o.game_id)}>
                {formatGameDate(o.game_date)} · game #{o.game_id}
              </option>
            ))}
          </select>
        </label>

        <label className="leg-form__field">
          <span className="leg-form__label">Stat</span>
          <select
            className="leg-form__input"
            value={statType}
            onChange={(e) => setStatType(e.target.value as StatType)}
          >
            {STAT_TYPES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        <label className="leg-form__field">
          <span className="leg-form__label">Line</span>
          <input
            className="leg-form__input"
            type="number"
            inputMode="decimal"
            step="0.5"
            value={line}
            onChange={(e) => setLine(e.target.value)}
            required
          />
        </label>

        <fieldset className="leg-form__field leg-form__fieldset">
          <legend className="leg-form__label">Side</legend>
          <div className="leg-form__segments">
            <button
              type="button"
              className={`leg-form__segment${direction === 'OVER' ? ' leg-form__segment--on' : ''}`}
              onClick={() => setDirection('OVER')}
            >
              Over
            </button>
            <button
              type="button"
              className={`leg-form__segment${direction === 'UNDER' ? ' leg-form__segment--on' : ''}`}
              onClick={() => setDirection('UNDER')}
            >
              Under
            </button>
          </div>
        </fieldset>
      </div>

      {submitErr && <p className="leg-form__err">{submitErr}</p>}

      <div className="leg-form__actions">
        <button type="submit" className="btn-primary">
          Add to slip
        </button>
      </div>
    </form>
  )
}
