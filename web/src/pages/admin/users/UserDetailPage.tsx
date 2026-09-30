import { Check, ChevronRight, Copy, KeyRound, ShieldCheck, UserX } from 'lucide-react';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';

import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { Dialog } from '@/components/ui/Dialog';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/contexts/ToastContext';

import { AdminColumn } from '../AdminLayout';
import { adminApi, bytes, device, maskIp, type UserDetailDTO } from '../api';
import { actionBtn, StateFeedback } from '../StateFeedback';
import { Card, CardHead, compact, fmt, relTime } from '../ui';

const SOURCE: Record<string, string> = { LOGIN: '账号登录', REGISTER: '注册后自动登录' };
const REASON: Record<string, string> = { BAD_PASSWORD: '密码错误', DISABLED: '账号已禁用' };

/** 设计稿 B5 用户详情：资料、用量统计、知识库、最近登录与启用 / 禁用 / 角色调整 */
export default function UserDetailPage() {
  const { userId } = useParams();
  const id = Number(userId);
  const toast = useToast();
  const { user: me } = useAuth();
  const [u, setU] = useState<UserDetailDTO | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<'disable' | 'role' | 'reset' | null>(null);
  const [tempPwd, setTempPwd] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    setError(null);
    adminApi
      .user(id)
      .then(setU)
      .catch((e: Error) => setError(e.message || '加载失败'));
  }, [id]);
  useEffect(reload, [reload]);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      toast(ok, { tone: 'success' });
      setConfirm(null);
      reload();
    } catch (e) {
      toast((e as Error).message || '操作失败', { tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const crumbs = (name: string) => (
    <nav aria-label="面包屑" className="flex items-center gap-1 text-[11px] text-muted">
      <Link to="/admin/users?tab=list" className="hover:text-ink">
        用户列表
      </Link>
      <ChevronRight aria-hidden className="size-3" />
      <span className="text-text2">{name}</span>
    </nav>
  );

  if (!u)
    return (
      <AdminColumn>
        {crumbs(`#${userId}`)}
        {error ? (
          <StateFeedback kind="error" size="page" title="用户详情加载失败" desc={error} action={<button type="button" onClick={reload} className={actionBtn}>重新加载</button>} />
        ) : (
          <StateFeedback kind="loading" size="page" title="正在加载" />
        )}
      </AdminColumn>
    );

  const name = u.nickname?.trim() || u.username;
  const self = me?.username === u.username;
  const s = u.stats;
  const toAdmin = u.role !== 'ADMIN';

  return (
    <AdminColumn>
      {crumbs(name)}
      <div className="mt-5 flex items-center gap-4">
        <span className="flex size-14 shrink-0 items-center justify-center rounded-full bg-active font-serif text-[22px] font-semibold text-ink">{name.slice(0, 1).toUpperCase()}</span>
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <h1 className="font-serif text-[24px] leading-tight font-semibold text-ink">{name}</h1>
            {u.role === 'ADMIN' ? <Chip tone="blue" dot={false}>管理员</Chip> : <Chip tone="gray" dot={false}>普通用户</Chip>}
            {u.status ? <Chip tone="green">启用</Chip> : <Chip tone="red">禁用</Chip>}
          </div>
          <p className="flex flex-wrap gap-x-3 font-num text-[12px] text-muted">
            <span>{u.email ?? u.username}</span>
            <span>ID {u.id}</span>
            <span>注册于 {u.createdAt?.slice(0, 10) ?? '—'}</span>
          </p>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2.5">
          <Button variant="secondary" icon={<ShieldCheck className="size-3.5" />} disabled={self || busy} title={self ? '不能修改自己的角色' : undefined} onClick={() => setConfirm('role')}>
            {toAdmin ? '设为管理员' : '取消管理员'}
          </Button>
          <Button variant="secondary" icon={<KeyRound className="size-3.5" />} disabled={self || busy} title={self ? '请在个人设置中修改自己的密码' : undefined} onClick={() => setConfirm('reset')}>
            重置密码
          </Button>
          {u.status ? (
            <Button variant="secondary" icon={<UserX className="size-3.5" />} disabled={self || busy} className="text-red" onClick={() => setConfirm('disable')}>
              禁用账号
            </Button>
          ) : (
            <Button variant="primary" disabled={busy} onClick={() => run(() => adminApi.setStatus(u.id, 1), '已启用账号')}>
              启用账号
            </Button>
          )}
        </div>
      </div>
      <div className="mt-6 h-px bg-divider" />

      <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="知识库" value={fmt(s.datasetCount)} sub={`共 ${fmt(s.fileCount)} 个文件 · ${bytes(s.fileBytes)}`} />
        <Stat label="对话" value={fmt(s.conversationCount)} sub={`近 30 天新建 ${fmt(s.conversations30d)} 个`} />
        <Stat label="近 30 天 Token" value={compact(s.tokens30d)} sub={`输入 ${compact(s.promptTokens30d)} · 输出 ${compact(s.completionTokens30d)}`} />
        <Stat label="自带模型配置" value={fmt(s.modelConfigCount)} sub={s.modelProviders.length ? s.modelProviders.join(' · ') : '未配置'} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[340px_1fr]">
        <Card className="flex flex-col gap-3.5 px-5 py-[18px]">
          <CardHead title="账号信息" />
          <dl className="flex flex-col gap-3 text-[12px]">
            <Row k="用户名" v={<span className="font-num">{u.username}</span>} />
            <Row k="邮箱" v={<span className="font-num">{u.email ?? '—'}</span>} />
            <Row k="手机" v={<span className="font-num">{u.phone ? u.phone.replace(/^(\d{3})\d{4}(\d+)$/, '$1 **** $2') : '—'}</span>} />
            <Row k="角色" v={u.role === 'ADMIN' ? '管理员 ADMIN' : '普通用户 USER'} />
            <Row k="团队" v={u.team ?? '—'} />
            <Row k="最近登录" v={u.lastLoginAt ? relTime(u.lastLoginAt) : '从未登录'} />
            <Row k="最近 IP" v={<span className="font-num">{maskIp(u.recentLogins.find((l) => l.success)?.ip)}</span>} />
            <Row k="最近设备" v={device(u.recentLogins.find((l) => l.success)?.userAgent)} />
          </dl>
        </Card>
        <div className="flex min-w-0 flex-col gap-4">
          <Card className="flex flex-col gap-3 px-5 py-[18px]">
            <CardHead title="知识库" extra={`${s.datasetCount} 个 · 只读查看`} />
            {u.datasets.length ? (
              <ul className="flex flex-col divide-y divide-divider">
                {u.datasets.slice(0, 6).map((d) => (
                  <li key={d.id} className="flex items-center gap-3 py-2.5 text-[12px]">
                    <span className="truncate font-medium text-ink">{d.name}</span>
                    <span className="text-muted">
                      {fmt(d.fileCount)} 个文件 · {bytes(d.fileBytes)}
                    </span>
                    <span className="ml-auto font-num text-[11px] text-muted">{relTime(d.updatedAt).replace(/ \d\d:\d\d$/, '')}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <StateFeedback kind="empty" size="inline" title="该用户还没有知识库" />
            )}
          </Card>
          <Card className="flex flex-col gap-3 px-5 py-[18px]">
            <CardHead
              title="最近登录记录"
              extra={
                <Link to={`/admin/logs?keyword=${encodeURIComponent(u.username)}&range=7d`} className="hover:text-ink">
                  查看日志 →
                </Link>
              }
            />
            {u.recentLogins.length ? (
              <ul className="flex flex-col divide-y divide-divider">
                {u.recentLogins.map((l, i) => (
                  <li key={i} className="grid grid-cols-[110px_120px_1fr_auto] items-center gap-3 py-2.5 text-[12px]">
                    <span className="font-num text-[11.5px] text-text2">{relTime(l.time)}</span>
                    <span className="font-num text-[11.5px] text-text2" title={l.ip ?? undefined}>
                      {maskIp(l.ip)}
                    </span>
                    <span className="truncate text-text2" title={l.userAgent ?? undefined}>
                      {device(l.userAgent)}
                      {l.success && l.source === 'REGISTER' && <span className="text-muted"> · {SOURCE.REGISTER}</span>}
                    </span>
                    {l.success ? <Chip tone="green">成功</Chip> : <Chip tone="red">{REASON[l.reason ?? ''] ?? '失败'}</Chip>}
                  </li>
                ))}
              </ul>
            ) : (
              <StateFeedback kind="empty" size="inline" title="暂无登录记录" />
            )}
          </Card>
        </div>
      </div>

      <Dialog
        open={confirm === 'disable'}
        onClose={() => setConfirm(null)}
        title="禁用账号"
        description={`${name} · ${u.email ?? u.username}`}
        icon={<UserX className="size-4 text-red" />}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirm(null)}>
              取消
            </Button>
            <Button variant="danger" disabled={busy} onClick={() => run(() => adminApi.setStatus(u.id, 0), '已禁用账号')}>
              确认禁用
            </Button>
          </>
        }
      >
        <p className="text-[13px] leading-5 text-text2">禁用后该用户将无法登录，已登录的会话在下次请求时失效；其知识库与对话数据保留，可随时重新启用。</p>
      </Dialog>
      <Dialog
        open={confirm === 'role'}
        onClose={() => setConfirm(null)}
        title={toAdmin ? '设为管理员' : '取消管理员'}
        description={name}
        icon={<ShieldCheck className="size-4 text-text2" />}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirm(null)}>
              取消
            </Button>
            <Button disabled={busy} onClick={() => run(() => adminApi.setRole(u.id, toAdmin ? 'ADMIN' : 'USER'), toAdmin ? '已设为管理员' : '已取消管理员')}>
              确认
            </Button>
          </>
        }
      >
        <p className="text-[13px] leading-5 text-text2">{toAdmin ? '管理员可以进入管理台，查看全部用户、管理博客、模型目录与日志。' : '取消后该用户将无法再进入管理台。'}</p>
      </Dialog>
      <Dialog
        open={confirm === 'reset'}
        onClose={() => (setConfirm(null), setTempPwd(null), setCopied(false))}
        title={tempPwd ? '密码已重置' : '重置密码'}
        description={`${name} · ${u.email ?? u.username}`}
        icon={<KeyRound className="size-4 text-text2" />}
        footer={
          tempPwd ? (
            <Button onClick={() => (setConfirm(null), setTempPwd(null), setCopied(false))}>完成</Button>
          ) : (
            <>
              <Button variant="secondary" onClick={() => setConfirm(null)}>
                取消
              </Button>
              <Button
                variant="danger"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const r = await adminApi.resetPassword(u.id);
                    setTempPwd(r.temporaryPassword ?? '');
                  } catch (e) {
                    toast((e as Error).message || '重置失败', { tone: 'error' });
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                确认重置
              </Button>
            </>
          )
        }
      >
        {tempPwd ? (
          <div className="flex flex-col gap-3">
            <p className="text-[13px] leading-5 text-text2">临时密码只显示这一次，请通过安全渠道告知用户，并提醒其登录后在个人设置中修改。</p>
            <div className="flex items-center gap-2 rounded-[10px] border border-line bg-soft px-3.5 py-3">
              <code className="flex-1 font-mono text-[15px] tracking-wide text-ink select-all">{tempPwd}</code>
              <button
                type="button"
                aria-label="复制临时密码"
                onClick={() => navigator.clipboard.writeText(tempPwd).then(() => setCopied(true), () => toast('复制失败，请手动选择复制', { tone: 'error' }))}
                className="flex items-center gap-1 rounded-[6px] px-2 py-1 text-[12px] text-text2 hover:bg-white"
              >
                {copied ? <Check className="size-3.5 text-green" /> : <Copy className="size-3.5" />}
                {copied ? '已复制' : '复制'}
              </button>
            </div>
          </div>
        ) : (
          <p className="text-[13px] leading-5 text-text2">将为该用户生成新的临时密码，原密码立即失效，已登录的会话会被强制下线。</p>
        )}
      </Dialog>
    </AdminColumn>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <Card className="flex flex-col gap-2 px-5 py-4">
      <p className="text-[11.5px] text-muted">{label}</p>
      <p className="font-num text-[24px] leading-tight font-semibold text-ink">{value}</p>
      <p className="truncate text-[11px] text-muted" title={sub}>
        {sub}
      </p>
    </Card>
  );
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-16 shrink-0 text-muted">{k}</dt>
      <dd className="min-w-0 truncate text-ink">{v}</dd>
    </div>
  );
}
