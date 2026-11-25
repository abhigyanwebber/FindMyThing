/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API base URL including the `/api` prefix (contract section 15). Build-time, public, never a secret. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
