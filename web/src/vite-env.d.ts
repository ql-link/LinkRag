/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 设为 'false' 时连接真实后端（默认使用内存 Mock） */
  readonly VITE_USE_MOCK?: string;
  /** Vite 开发代理目标，默认 http://localhost:8000 */
  readonly VITE_API_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
