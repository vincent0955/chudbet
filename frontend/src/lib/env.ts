const DEFAULT_DEV_API = 'http://localhost:8000'

/**
 * Base URL for API requests. Set `VITE_API_URL` in `.env.development` / `.env.local`.
 * Defaults to the local FastAPI server when unset.
 */
export function getApiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_URL
  if (typeof raw === 'string' && raw.trim().length > 0) {
    return raw.replace(/\/$/, '')
  }
  return DEFAULT_DEV_API
}

/**
 * Configured wallet account id (must match a row in `accounts`). When unset or invalid, returns null.
 */
export function getConfiguredAccountId(): number | null {
  const raw = import.meta.env.VITE_ACCOUNT_ID
  if (raw === undefined || raw === null || String(raw).trim() === '') return null
  const n = Number.parseInt(String(raw).trim(), 10)
  if (!Number.isFinite(n) || n < 1) return null
  return n
}
