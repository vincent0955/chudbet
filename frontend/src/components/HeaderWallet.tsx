import { useWallet } from '../context/WalletContext'
import { formatUsdFromCents } from '../lib/formatMoney'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

function ProfileIcon() {
  return (
    <svg
      className="app-header__profile-icon"
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  )
}

export function HeaderWallet() {
  const { user, accountId, balanceCents, loading, error, guestLogin, logout, login, addMoney } = useWallet()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loginErr, setLoginErr] = useState<string | null>(null)

  const balanceLabel =
    error != null ? '—' : loading && balanceCents == null ? '…' : formatUsdFromCents(balanceCents ?? 0)

  return (
    <div className="app-header__wallet">
      {user != null && accountId != null && (
        <span
          className={`app-header__balance${error ? ' app-header__balance--error' : ''}`}
          title={error ?? 'Account balance'}
          aria-live="polite"
        >
          {balanceLabel}
        </span>
      )}

      <details className="app-header__profile">
        <summary className="app-header__profile-btn" aria-label="Profile menu">
          <ProfileIcon />
        </summary>
        <div className="app-header__profile-menu" role="menu">
          {user == null || accountId == null ? (
            <>
              <p className="app-header__profile-row muted">Logged out</p>
              <input
                className="app-header__profile-input"
                type="email"
                placeholder="Email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <input
                className="app-header__profile-input"
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {loginErr && <p className="app-header__profile-err">{loginErr}</p>}
              <button
                type="button"
                className="app-header__profile-action"
                onClick={async () => {
                  try {
                    setLoginErr(null)
                    await login(email, password)
                  } catch (e) {
                    setLoginErr(e instanceof Error ? e.message : 'Login failed')
                  }
                }}
              >
                Log in
              </button>
              <button type="button" className="app-header__profile-action" onClick={() => navigate('/signup')}>
                Sign up
              </button>
              <button type="button" className="app-header__profile-action" onClick={() => void guestLogin()}>
                Log in as guest
              </button>
            </>
          ) : (
            <>
              <p className="app-header__profile-row muted">{user.is_guest ? 'Guest wallet' : user.username}</p>
              <p className="app-header__profile-row">
                Account <span className="app-header__profile-mono">#{accountId}</span>
              </p>
              {error && <p className="app-header__profile-err">{error}</p>}
              <button
                type="button"
                className="app-header__profile-action"
                onClick={async () => {
                  const raw = typeof window !== 'undefined' ? window.prompt('Deposit amount in USD', '100') : null
                  if (!raw) return
                  const n = Number.parseFloat(raw)
                  if (!Number.isFinite(n) || n <= 0) return
                  await addMoney(Math.round(n * 100))
                }}
              >
                Add money
              </button>
              <button type="button" className="app-header__profile-action" onClick={() => void logout()}>
                Log out
              </button>
            </>
          )}
        </div>
      </details>
    </div>
  )
}
