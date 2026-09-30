/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 设为 'false' 时连接真实后端（默认使用内存 Mock） */
  readonly VITE_USE_MOCK?: string;
  /** Vite 开发代理目标，默认 http://localhost:8000 */
  readonly VITE_API_TARGET?: string;
  /** 落地页 GitHub / 博客 / 反馈链接指向的仓库地址 */
  readonly VITE_GITHUB_URL?: string;
  /** 社群：微信群 / QQ 群二维码图片地址（可放在 public/ 下），微信助手号、QQ 一键加群链接 */
  readonly VITE_WECHAT_QR_URL?: string;
  readonly VITE_WECHAT_ID?: string;
  readonly VITE_QQ_QR_URL?: string;
  readonly VITE_QQ_JOIN_URL?: string;
  /** 联系邮箱与安全问题邮箱 */
  readonly VITE_CONTACT_EMAIL?: string;
  readonly VITE_SECURITY_EMAIL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
