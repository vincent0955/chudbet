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
import { getAccount } from '../api/endpoints'
import { getConfiguredAccountId } from '../lib/env'

type WalletContextValue = {
  accountId: number | null
  balanceCents: number | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

const WalletContext = createContext<WalletContextValue | null>(null)

export function WalletProvider({ children }: { children: ReactNode }) {
  const accountId = useMemo(() => getConfiguredAccountId(), [])
  const [balanceCents, setBalanceCents] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (accountId == null) {
      setLoading(false)
      setBalanceCents(null)
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const acc = await getAccount(accountId)
      setBalanceCents(acc.balance_cents)
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.status === 404 ? 'Wallet not found for this account id.' : e.message)
      } else {
        setError(e instanceof Error ? e.message : 'Could not load balance.')
      }
      setBalanceCents(null)
    } finally {
      setLoading(false)
    }
  }, [accountId])

  useEffect(() => {
    startTransition(() => {
      void refresh()
    })
  }, [refresh])

  useEffect(() => {
    if (accountId == null) return
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
  }, [accountId, refresh])

  const value = useMemo(
    () => ({
      accountId,
      balanceCents,
      loading,
      error,
      refresh,
    }),
    [accountId, balanceCents, loading, error, refresh],
  )

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components -- useWallet is a valid companion export
export function useWallet(): WalletContextValue {
  const ctx = useContext(WalletContext)
  if (!ctx) throw new Error('useWallet must be used within WalletProvider')
  return ctx
}
