import { ArrowRight, Eye, EyeOff, Loader2, Lock, Mail, User } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/Button';
import { Field, TextInput } from '@/components/ui/Field';
import { Segmented } from '@/components/ui/Segmented';
import { AuthError, useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/contexts/ToastContext';

import { AuthLayout } from './AuthLayout';
import { validateRegister, type RegisterErrors } from './validation';

type Mode = 'login' | 'register';

function PasswordInput({ id, value, onChange, placeholder, invalid, describedBy, autoComplete }: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  invalid?: boolean;
  describedBy?: string;
  autoComplete: string;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <TextInput
      id={id}
      height={42}
      type={visible ? 'text' : 'password'}
      icon={<Lock />}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      invalid={invalid}
      aria-describedby={describedBy}
      autoComplete={autoComplete}
      trailing={
        <button type="button" onClick={() => setVisible((v) => !v)} aria-label={visible ? '隐藏密码' : '显示密码'} className="text-muted hover:text-ink">
          {visible ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
        </button>
      }
    />
  );
}

/** A1 登录 / A2 注册 / A3 校验与错误 */
export default function AuthPage({ mode }: { mode: Mode }) {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();

  const [account, setAccount] = useState('');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<RegisterErrors & { account?: string }>({});
  const [loading, setLoading] = useState(false);

  if (user) return <Navigate to="/datasets" replace />;
  const from = (location.state as { from?: string } | null)?.from ?? '/datasets';

  const switchMode = (m: Mode) => {
    setErrors({});
    navigate(m === 'login' ? '/login' : '/register');
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (mode === 'login') {
      const next: typeof errors = {};
      if (!account.trim()) next.account = '请输入用户名或邮箱';
      if (!password) next.password = '请输入密码';
      setErrors(next);
      if (Object.keys(next).length) return;
    } else {
      const next = validateRegister({ username, email, password, confirm });
      setErrors(next);
      if (Object.keys(next).length) {
        toast('注册失败：请检查表单信息', { tone: 'error' });
        return;
      }
    }
    setLoading(true);
    try {
      if (mode === 'login') await login(account.trim(), password);
      else await register({ username: username.trim(), email: email.trim(), password });
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof AuthError && err.field) setErrors({ [err.field]: err.message });
      toast(mode === 'login' ? `登录失败：${(err as Error).message}` : '注册失败：请检查表单信息', { tone: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const isLogin = mode === 'login';

  return (
    <AuthLayout>
      <form className="auth-form" onSubmit={submit} noValidate>
        <p className="text-[11px] text-muted">{isLogin ? '登录 LinkRag' : '创建账号'}</p>
        <h1 className="mt-2 font-serif text-[28px] font-semibold text-ink">{isLogin ? '欢迎回来' : '创建知识空间'}</h1>
        <p className="mt-2 text-[13px] text-text2">{isLogin ? '登录后继续使用你的知识空间。' : '创建账号，开始整理和检索资料。'}</p>
        <div className="mt-[26px]">
          <Segmented
            size="lg"
            block
            ariaLabel="登录或注册"
            value={mode}
            onChange={switchMode}
            options={[
              { value: 'login', label: '登录' },
              { value: 'register', label: '注册' },
            ]}
          />
        </div>
        <div className="mt-6 flex flex-col gap-4">
          {isLogin ? (
            <>
              <Field label="账号" hint="用户名或邮箱" error={errors.account}>
                {(id, d) => (
                  <TextInput id={id} height={42} icon={<User />} value={account} onChange={(e) => setAccount(e.target.value)} invalid={!!errors.account} aria-describedby={d} autoComplete="username" placeholder="chenmo" />
                )}
              </Field>
              <Field label="密码" error={errors.password}>
                {(id, d) => <PasswordInput id={id} value={password} onChange={setPassword} invalid={!!errors.password} describedBy={d} autoComplete="current-password" placeholder="输入密码" />}
              </Field>
            </>
          ) : (
            <>
              <Field label="用户名" hint="3–20 位字母、数字或下划线" error={errors.username}>
                {(id, d) => (
                  <TextInput id={id} height={42} icon={<User />} value={username} onChange={(e) => setUsername(e.target.value)} invalid={!!errors.username} aria-describedby={d} autoComplete="username" placeholder="chenmo" />
                )}
              </Field>
              <Field label="邮箱" error={errors.email}>
                {(id, d) => (
                  <TextInput id={id} height={42} type="email" icon={<Mail />} value={email} onChange={(e) => setEmail(e.target.value)} invalid={!!errors.email} aria-describedby={d} autoComplete="email" placeholder="name@example.com" />
                )}
              </Field>
              <Field label="密码" hint="至少 8 位，包含字母与数字" error={errors.password}>
                {(id, d) => <PasswordInput id={id} value={password} onChange={setPassword} invalid={!!errors.password} describedBy={d} autoComplete="new-password" placeholder="设置密码" />}
              </Field>
              <Field label="确认密码" error={errors.confirm}>
                {(id, d) => <PasswordInput id={id} value={confirm} onChange={setConfirm} invalid={!!errors.confirm} describedBy={d} autoComplete="new-password" placeholder="再次输入密码" />}
              </Field>
            </>
          )}
        </div>
        <div className="mt-6">
          <Button
            type="submit"
            size="lg"
            block
            disabled={loading}
            icon={loading ? <Loader2 className="size-3 animate-spin" /> : undefined}
            trailingIcon={loading ? undefined : <ArrowRight className="size-3" />}
          >
            {loading ? '处理中…' : isLogin ? '登录' : '创建账号'}
          </Button>
        </div>
        <p className="mt-[18px] flex justify-center gap-1 text-[12px]">
          <span className="text-muted">{isLogin ? '还没有账号？' : '已经有账号？'}</span>
          <Link to={isLogin ? '/register' : '/login'} className="font-medium text-ink hover:underline">
            {isLogin ? '注册' : '登录'}
          </Link>
        </p>
      </form>
    </AuthLayout>
  );
}

