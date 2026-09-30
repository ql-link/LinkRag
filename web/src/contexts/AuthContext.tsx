import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

import { authApi, type ProfileDTO } from '@/api/endpoints';
import { ApiError, getToken, setToken, setUnauthorizedHandler, USE_MOCK } from '@/api/http';
import { delay } from '@/mock/db';
import { hydrateFromBackend, resetBackendState } from '@/services/backend';
import { startOnboarding } from '@/services/home';
import type { User } from '@/types';

/**
 * 登录态。真实模式（VITE_USE_MOCK=false）对接 Python `/api/v1/auth/*` 与 `/api/v1/user/*`：
 * access token 存 localStorage，用户资料缓存到 localStorage 以便刷新页面时立即渲染，再异步校正。
 * Mock 模式保留原有本地模拟逻辑（离线演示与单元测试）。
 */
interface AuthValue {
  user: User | null;
  login: (account: string, password: string) => Promise<void>;
  register: (input: { username: string; email: string; password: string }) => Promise<void>;
  logout: () => void;
  /** 修改个人资料：对应 PATCH /api/v1/user/profile */
  updateProfile: (patch: Partial<Pick<User, 'displayName' | 'email' | 'bio' | 'team'>>) => Promise<void>;
  /** 修改登录密码：对应 POST /api/v1/user/password（成功后其他会话失效） */
  changePassword: (current: string, next: string) => Promise<void>;
}

const STORAGE_KEY = 'linkrag.user';
const TAKEN_USERNAMES = ['admin', 'root', 'linkrag'];

const AuthContext = createContext<AuthValue | null>(null);

function readUser(): User | null {
  if (!USE_MOCK && !getToken()) return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export class AuthError extends Error {
  constructor(
    message: string,
    public field?: 'account' | 'password' | 'username' | 'email' | 'current',
  ) {
    super(message);
  }
}

function toUser(p: ProfileDTO): User {
  return {
    username: p.username,
    displayName: p.nickname?.trim() || p.username,
    email: p.email ?? '',
    bio: p.bio ?? undefined,
    team: p.team ?? undefined,
    createdAt: p.createdAt?.slice(0, 10) ?? undefined,
    role: p.role,
  };
}

/** 后端业务码 → 表单字段错误（错误码见 docs/api/error_codes.md） */
function authError(e: unknown): Error {
  if (!(e instanceof ApiError)) return e as Error;
  switch (e.code) {
    case 20001:
      return new AuthError('账号不存在', 'account');
    case 20002:
      return new AuthError('账号或密码错误', 'password');
    case 20003:
      return new AuthError('账号已被禁用', 'account');
    case 20006:
      return new AuthError('该用户名已被占用', 'username');
    case 20007:
      return new AuthError('该邮箱已被使用', 'email');
    case 20008:
      return new AuthError('当前密码不正确', 'current');
    case 20009:
      return new AuthError('新密码不能与当前密码相同', 'password');
    default:
      return new AuthError(e.message);
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(readUser);

  const persist = (u: User) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(u));
    setUser(u);
  };

  const clear = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setToken(null);
    resetBackendState();
    setUser(null);
  }, []);

  // 真实模式：token 失效（401）统一退出；启动时用后端资料校正本地缓存并加载业务数据
  useEffect(() => {
    if (USE_MOCK) return;
    setUnauthorizedHandler(clear);
    if (getToken()) {
      authApi
        .profile()
        .then((p) => persist(toUser(p)))
        .catch(() => undefined);
      void hydrateFromBackend();
    }
    return () => setUnauthorizedHandler(undefined);
  }, [clear]);

  const signIn = async (result: Awaited<ReturnType<typeof authApi.login>>) => {
    setToken(result);
    persist(toUser(await authApi.profile()));
    void hydrateFromBackend();
  };

  const login = useCallback(async (account: string, password: string) => {
    if (!USE_MOCK) {
      try {
        await signIn(await authApi.login(account.trim(), password));
      } catch (e) {
        throw authError(e);
      }
      return;
    }
    await delay(500);
    if (password.length < 6) throw new AuthError('账号或密码错误', 'password');
    const username = account.includes('@') ? account.split('@')[0] : account;
    persist({ username, displayName: username === 'chenmo' ? '陈默' : username, email: account.includes('@') ? account : `${account}@example.com`, createdAt: '2026-03-12', role: 'ADMIN' });
  }, []);

  const register = useCallback(async (input: { username: string; email: string; password: string }) => {
    if (!USE_MOCK) {
      try {
        await signIn(await authApi.register(input.username, input.email, input.password));
      } catch (e) {
        throw authError(e);
      }
      startOnboarding();
      return;
    }
    await delay(700);
    if (TAKEN_USERNAMES.includes(input.username.toLowerCase())) throw new AuthError('该用户名已被占用', 'username');
    persist({ username: input.username, displayName: input.username, email: input.email, createdAt: new Date().toISOString().slice(0, 10) });
    startOnboarding();
  }, []);

  const logout = useCallback(() => {
    // 先撤销服务端会话，再清理本地（撤销失败也要退出）
    if (!USE_MOCK && getToken()) void authApi.logout().catch(() => undefined);
    clear();
  }, [clear]);

  const updateProfile = useCallback<AuthValue['updateProfile']>(async (patch) => {
    const current = readUser();
    if (!USE_MOCK) {
      try {
        await authApi.updateProfile({ nickname: patch.displayName, email: patch.email, bio: patch.bio, team: patch.team });
        persist(toUser(await authApi.profile()));
      } catch (e) {
        throw authError(e);
      }
      return;
    }
    await delay(400);
    if (!current) return;
    persist({ ...current, ...patch });
  }, []);

  const changePassword = useCallback(async (current: string, next: string) => {
    if (!USE_MOCK) {
      try {
        // 成功后旧 token 全部失效，换用响应里为当前客户端新签发的 token
        setToken(await authApi.changePassword(current, next));
      } catch (e) {
        throw authError(e);
      }
      return;
    }
    await delay(500);
    if (current.length < 6) throw new AuthError('当前密码不正确', 'current');
    if (next === current) throw new AuthError('新密码不能与当前密码相同', 'password');
  }, []);

  return <AuthContext.Provider value={{ user, login, register, logout, updateProfile, changePassword }}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
