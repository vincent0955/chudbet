import {
  createContext,
  startTransition,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { ApiError } from '../api/client'
import { deposit, getAuthMe, login, loginGuest, logout, signup } from '../api/endpoints'
import type { UserRead } from '../api/types'

type WalletContextValue = {
  user: UserRead | null
  accountId: number | null
  balanceCents: number | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  login: (email: string, password: string) => Promise<void>
  signup: (email: string, username: string, password: string) => Promise<void>
  guestLogin: () => Promise<void>
  logout: () => Promise<void>
  addMoney: (amountCents: number) => Promise<void>
}

const WalletContext = createContext<WalletContextValue | null>(null)

export function WalletProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null)
  const [accountId, setAccountId] = useState<number | null>(null)
  const [balanceCents, setBalanceCents] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const me = await getAuthMe()
      setUser(me.user)
      setAccountId(me.account_id)
      setBalanceCents(me.balance_cents)
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.status === 401) {
          setUser(null)
          setAccountId(null)
          setBalanceCents(null)
          setError(null)
          return
        }
        setError(e.message)
      } else {
        setError(e instanceof Error ? e.message : 'Could not load balance.')
      }
      setUser(null)
      setAccountId(null)
      setBalanceCents(null)
    } finally {
      setLoading(false)
    }
  }, [])

  const loginWithPassword = useCallback(async (email: string, password: string) => {
    const me = await login({ email, password })
    setUser(me.user)
    setAccountId(me.account_id)
    setBalanceCents(me.balance_cents)
    setError(null)
  }, [])

  const signupWithPassword = useCallback(async (email: string, username: string, password: string) => {
    const me = await signup({ email, username, password })
    setUser(me.user)
    setAccountId(me.account_id)
    setBalanceCents(me.balance_cents)
    setError(null)
  }, [])

  const guestLogin = useCallback(async () => {
    const me = await loginGuest()
    setUser(me.user)
    setAccountId(me.account_id)
    setBalanceCents(me.balance_cents)
    setError(null)
  }, [])

  const logoutUser = useCallback(async () => {
    try {
      await logout()
    } catch {
      // Even if network/logout endpoint fails, force local signed-out state.
    } finally {
      setUser(null)
      setAccountId(null)
      setBalanceCents(null)
      setError(null)
    }
  }, [])

  const addMoney = useCallback(
    async (amountCents: number) => {
      if (accountId == null) throw new Error('Not logged in')
      await deposit(accountId, {
        amount_cents: amountCents,
        idempotency_key:
          typeof crypto !== 'undefined' && crypto.randomUUID
            ? crypto.randomUUID()
            : `dep-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        memo: 'Manual top-up',
      })
      await refresh()
    },
    [accountId, refresh],
  )

  useEffect(() => {
    startTransition(() => {
      void refresh()
    })
  }, [refresh])

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        startTransition(() => void refresh())
      }
    }
    const onFocus = () => startTransition(() => void refresh())
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [refresh])

  const value = useMemo(
    () => ({
      user,
      accountId,
      balanceCents,
      loading,
      error,
      refresh,
      login: loginWithPassword,
      signup: signupWithPassword,
      guestLogin,
      logout: logoutUser,
      addMoney,
    }),
    [
      user,
      accountId,
      balanceCents,
      loading,
      error,
      refresh,
      loginWithPassword,
      signupWithPassword,
      guestLogin,
      logoutUser,
      addMoney,
    ],
  )

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components -- useWallet is a valid companion export
export function useWallet(): WalletContextValue {
  const ctx = useContext(WalletContext)
  if (!ctx) throw new Error('useWallet must be used within WalletProvider')
  return ctx
}
