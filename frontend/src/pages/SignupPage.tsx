import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useWallet } from '../context/WalletContext'

export function SignupPage() {
  const navigate = useNavigate()
  const { signup, guestLogin } = useWallet()
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  return (
    <section className="page card signup-page">
      <h1 className="page-title">Sign up</h1>
      <div className="signup-page__fields">
        <input
          className="app-header__profile-input"
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          className="app-header__profile-input"
          type="text"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          className="app-header__profile-input"
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <input
          className="app-header__profile-input"
          type="password"
          placeholder="Confirm password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
        />
      </div>
      {err && <p className="app-header__profile-err">{err}</p>}
      <button
        type="button"
        className="btn-primary"
        disabled={submitting}
        onClick={async () => {
          if (password !== confirmPassword) {
            setErr('Passwords do not match')
            return
          }
          try {
            setSubmitting(true)
            setErr(null)
            await signup(email, username, password)
            navigate('/')
          } catch (e) {
            setErr(e instanceof Error ? e.message : 'Sign up failed')
          } finally {
            setSubmitting(false)
          }
        }}
      >
        {submitting ? 'Signing up…' : 'Sign up'}
      </button>
      <button
        type="button"
        className="btn-text"
        onClick={async () => {
          try {
            setErr(null)
            await guestLogin()
            navigate('/')
          } catch (e) {
            setErr(e instanceof Error ? e.message : 'Guest login failed')
          }
        }}
      >
        Log in as guest
      </button>
      <p className="muted">
        Already have an account? <Link to="/" className="inline-link">Log in from profile</Link>
      </p>
    </section>
  )
}
