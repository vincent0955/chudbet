import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { BetSlip } from '../components/BetSlip'
import { HeaderWallet } from '../components/HeaderWallet'

function showBetSlipPath(pathname: string): boolean {
  if (pathname === '/' || pathname === '') return true
  if (pathname === '/mlb' || pathname.startsWith('/mlb/games/')) return true
  const parts = pathname.split('/').filter(Boolean)
  return parts.length === 2 && parts[0] === 'games'
}

function myBetsNavActive(pathname: string, isActiveLink: boolean): boolean {
  return isActiveLink || pathname.startsWith('/bets')
}

export function AppLayout() {
  const { pathname } = useLocation()
  const showSlip = showBetSlipPath(pathname)

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__inner">
          <div className="app-header__left">
            <Link to="/" className="app-brand">
              ChudBet
            </Link>
            <nav className="app-nav" aria-label="Main">
              <NavLink
                to="/"
                end
                className={({ isActive }) =>
                  `app-nav__link${isActive ? ' app-nav__link--active' : ''}`
                }
              >
                NBA
              </NavLink>
              <NavLink
                to="/mlb"
                className={({ isActive }) =>
                  `app-nav__link${isActive ? ' app-nav__link--active' : ''}`
                }
              >
                MLB
              </NavLink>
              <NavLink
                to="/bets/open"
                className={({ isActive }) =>
                  `app-nav__link${myBetsNavActive(pathname, isActive) ? ' app-nav__link--active' : ''}`
                }
              >
                My Bets
              </NavLink>
            </nav>
          </div>
          <div className="app-header__right">
            <HeaderWallet />
          </div>
        </div>
      </header>

      <div className="app-main-gutter">
        <div className={`app-body${showSlip ? ' app-body--with-slip' : ''}`}>
          {showSlip ? (
            <div className="app-body__cluster">
              <main className="app-body__main">
                <Outlet />
              </main>
              <aside className="app-body__slip" aria-label="Bet slip">
                <BetSlip />
              </aside>
            </div>
          ) : (
            <main className="app-body__main">
              <Outlet />
            </main>
          )}
        </div>
      </div>
    </div>
  )
}
