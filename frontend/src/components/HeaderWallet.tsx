import { useWallet } from '../context/WalletContext'
import { formatUsdFromCents } from '../lib/formatMoney'

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
  const { accountId, balanceCents, loading, error, refresh } = useWallet()

  if (accountId == null) {
    return (
      <div className="app-header__wallet app-header__wallet--unconfigured">
        <span className="app-header__balance muted" title="Set VITE_ACCOUNT_ID in .env.development">
          No wallet
        </span>
        <div className="app-header__profile-wrap" aria-hidden>
          <div className="app-header__profile-btn app-header__profile-btn--static">
            <ProfileIcon />
          </div>
        </div>
      </div>
    )
  }

  const balanceLabel =
    error != null ? '—' : loading && balanceCents == null ? '…' : formatUsdFromCents(balanceCents ?? 0)

  return (
    <div className="app-header__wallet">
      <span
        className={`app-header__balance${error ? ' app-header__balance--error' : ''}`}
        title={error ?? 'Account balance'}
        aria-live="polite"
      >
        {balanceLabel}
      </span>

      <details className="app-header__profile">
        <summary className="app-header__profile-btn" aria-label="Profile menu">
          <ProfileIcon />
        </summary>
        <div className="app-header__profile-menu" role="menu">
          <p className="app-header__profile-row muted">Demo wallet</p>
          <p className="app-header__profile-row">
            Account <span className="app-header__profile-mono">#{accountId}</span>
          </p>
          {error && <p className="app-header__profile-err">{error}</p>}
          <button type="button" className="app-header__profile-action" onClick={() => void refresh()}>
            Refresh balance
          </button>
        </div>
      </details>
    </div>
  )
}
