import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { BetSlip } from '../components/BetSlip'

export function AppLayout() {
  const { pathname } = useLocation()
  const showSlip = pathname === '/' || pathname === ''

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__left">
          <Link to="/" className="app-brand">
            Chudbet
          </Link>
          <nav className="app-nav" aria-label="Main">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `app-nav__link${isActive ? ' app-nav__link--active' : ''}`
              }
            >
              Home
            </NavLink>
          </nav>
        </div>
      </header>

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
  )
}
