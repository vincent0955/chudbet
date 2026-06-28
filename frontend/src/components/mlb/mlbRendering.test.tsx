import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { MLBUpcomingGames } from './MLBUpcomingGames'
import { MLBPropBoard } from './MLBPropBoard'
import { AppLayout } from '../../layouts/AppLayout'
import { BetSlipProvider } from '../../context/BetSlipContext'

vi.mock('../../api', () => ({
  ApiError: class ApiError extends Error {
    status: number
    constructor(message: string, status = 500) {
      super(message)
      this.status = status
    }
  },
  getHealth: vi.fn().mockResolvedValue({ ok: true }),
  listMlbGames: vi.fn(),
  listMlbTeams: vi.fn(),
  getMlbGameMarkets: vi.fn(),
}))

vi.mock('../../components/HeaderWallet', () => ({ HeaderWallet: () => null }))
vi.mock('../../components/BetSlip', () => ({ BetSlip: () => null }))
vi.mock('../../context/WalletContext', () => ({
  WalletProvider: ({ children }: { children: React.ReactNode }) => children,
  useWallet: () => ({
    user: null,
    accountId: 1,
    balanceCents: 0,
    loading: false,
    error: null,
    refresh: async () => {},
    login: async () => {},
    signup: async () => {},
    guestLogin: async () => {},
    logout: async () => {},
    addMoney: async () => {},
  }),
}))

import { getMlbGameMarkets, listMlbGames, listMlbTeams } from '../../api'

function withSlip(ui: React.ReactNode) {
  return (
    <MemoryRouter>
      <BetSlipProvider>{ui}</BetSlipProvider>
    </MemoryRouter>
  )
}

describe('MLBUpcomingGames', () => {
  beforeEach(() => {
    vi.mocked(listMlbGames).mockReset()
    vi.mocked(listMlbTeams).mockReset()
    vi.mocked(getMlbGameMarkets).mockReset()
  })

  it('shows empty slate message when MLB collections are empty (Req 12.6)', async () => {
    vi.mocked(listMlbGames).mockResolvedValue([])
    vi.mocked(listMlbTeams).mockResolvedValue([])
    render(withSlip(<MLBUpcomingGames />))
    await waitFor(() => {
      expect(screen.getByText(/no mlb content available/i)).toBeTruthy()
    })
  })

  it('shows unavailable message on failed fetch with no partial content (Req 12.7)', async () => {
    vi.mocked(listMlbGames).mockRejectedValue(new Error('network down'))
    render(withSlip(<MLBUpcomingGames />))
    await waitFor(() => {
      expect(screen.getByText(/mlb data currently unavailable/i)).toBeTruthy()
    })
    expect(screen.queryByRole('listitem')).toBeNull()
  })

  it('renders Run Line / ML / Total headers when games exist (Req 12.2)', async () => {
    vi.mocked(listMlbGames).mockResolvedValue([
      {
        id: 1,
        home_team_id: 10,
        away_team_id: 11,
        game_date: '2026-06-15',
        status: 'Scheduled',
        mlb_game_id: '777',
      },
    ])
    vi.mocked(listMlbTeams).mockResolvedValue([
      { id: 10, name: 'Home', mlb_team_id: 110, abbreviation: 'HH' },
      { id: 11, name: 'Away', mlb_team_id: 111, abbreviation: 'AA' },
    ])
    vi.mocked(getMlbGameMarkets).mockResolvedValue({
      game: {
        id: 1,
        home_team_id: 10,
        away_team_id: 11,
        game_date: '2026-06-15',
        status: 'Scheduled',
        mlb_game_id: '777',
      },
      lookback: 10,
      sample_games_home: 0,
      sample_games_away: 0,
      moneyline: { home_american: '-120', away_american: '+100' },
      spread: {
        home_line: -1.5,
        home_american: '-110',
        away_line: 1.5,
        away_american: '-110',
      },
      total: { line: 8.5, over_american: '-105', under_american: '-115' },
    })
    render(withSlip(<MLBUpcomingGames />))
    await waitFor(() => {
      expect(screen.getByText('Run Line')).toBeTruthy()
      expect(screen.getByText('ML')).toBeTruthy()
      expect(screen.getByText('Total')).toBeTruthy()
    })
  })
})

describe('MLBPropBoard', () => {
  it('renders one column per offered stat type (Req 12.3)', () => {
    render(
      withSlip(
        <MLBPropBoard
        bundle={{
          game: {
            id: 5,
            home_team_id: 1,
            away_team_id: 2,
            game_date: '2026-06-15',
            status: 'Scheduled',
            mlb_game_id: '1',
          },
          lookback_days: 30,
          min_samples: 5,
          players: [
            {
              id: 99,
              full_name: 'Slugger',
              team_id: 1,
              team_name: 'Home',
              mlb_team_id: 10,
              mlb_player_id: 20,
              primary_position: 'OF',
              sample_size: 8,
              stat_lines: [
                {
                  stat_type: 'HITS',
                  thresholds: [
                    { threshold: 1, line: 0.5, american: '-200', under_american: '+160' },
                    { threshold: 2, line: 1.5, american: '+250', under_american: '-320' },
                    { threshold: 3, line: 2.5, american: '+900', under_american: '-1400' },
                  ],
                },
                {
                  stat_type: 'RUNS',
                  thresholds: [
                    { threshold: 1, line: 0.5, american: '-120', under_american: '-105' },
                    { threshold: 2, line: 1.5, american: '+400', under_american: '-560' },
                    { threshold: 3, line: 2.5, american: '+1200', under_american: '-2000' },
                  ],
                },
              ],
            },
          ],
        }}
        />,
      ),
    )
    expect(screen.getByText('Hits')).toBeTruthy()
    expect(screen.getByText('Runs')).toBeTruthy()
    expect(screen.getAllByText('Slugger').length).toBeGreaterThan(0)
  })
})

describe('AppLayout MLB nav', () => {
  it('renders the MLB nav link (Req 12.1)', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<div>Home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'MLB' }).getAttribute('href')).toBe('/mlb')
  })
})
