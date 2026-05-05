/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL for the Chudbet API (no trailing slash). Local default: http://localhost:8000 */
  readonly VITE_API_URL?: string
  /** Wallet account id (`GET /accounts/{id}`). Match backend CHUDBET_DEMO_ACCOUNT_ID when seeded. */
  readonly VITE_ACCOUNT_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
