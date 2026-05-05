/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL for the Chudbet API (no trailing slash). Local default: http://localhost:8000 */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
