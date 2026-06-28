const DEFAULT_DEV_API = 'http://localhost:8000'

/**
 * Base URL for API requests.
 *
 * - In dev, when `VITE_API_URL` is unset, requests use same-origin paths so the
 *   Vite dev-server proxy forwards to FastAPI (avoids CORS when Vite picks another port).
 * - Set `VITE_API_URL` in `.env.development` / `.env.local` to call the API directly.
 */
export function getApiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_URL
  if (typeof raw === 'string' && raw.trim().length > 0) {
    return raw.replace(/\/$/, '')
  }
  if (import.meta.env.DEV) {
    return ''
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
