export interface RegisterInput {
  username: string;
  email: string;
  password: string;
  confirm: string;
}

export type RegisterErrors = Partial<Record<keyof RegisterInput, string>>;

const USERNAME_RE = /^[A-Za-z0-9_]{3,20}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** 注册表单前端校验；规则与设计稿中的提示文案一致 */
export function validateRegister(v: RegisterInput): RegisterErrors {
  const e: RegisterErrors = {};
  if (!USERNAME_RE.test(v.username.trim())) e.username = '用户名需为 3–20 位字母、数字或下划线';
  if (!EMAIL_RE.test(v.email.trim())) e.email = '请输入有效的邮箱地址';
  if (v.password.length < 8 || !/[A-Za-z]/.test(v.password) || !/\d/.test(v.password)) e.password = '密码至少 8 位，且包含字母与数字';
  if (!v.confirm) e.confirm = '请再次输入密码';
  else if (v.confirm !== v.password) e.confirm = '两次输入的密码不一致';
  return e;
}
