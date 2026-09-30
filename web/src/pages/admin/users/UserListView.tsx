import { Download } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { Chip } from '@/components/ui/Chip';
import { SearchBox } from '@/components/ui/SearchBox';
import { Segmented } from '@/components/ui/Segmented';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';

import { adminApi, type AdminUserDTO, type UserQuery } from '../api';
import { actionBtn, StaleBanner, StateFeedback } from '../StateFeedback';
import { compact, fmt, Pagination, relTime, td, th } from '../ui';

const PAGE_SIZE = 20;
type RoleF = 'all' | 'USER' | 'ADMIN';
type StatusF = 'all' | '1' | '0';

/** 当前页导出 CSV（全量导出需后端支持，当前按页导出） */
function exportCsv(rows: AdminUserDTO[]) {
  const head = ['ID', '用户名', '昵称', '邮箱', '角色', '状态', '知识库', '近30天Token', '注册时间', '最近登录'];
  const esc = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const body = rows.map((u) => [u.id, u.username, u.nickname, u.email, u.role, u.status ? '启用' : '禁用', u.datasetCount, u.tokens30d, u.createdAt, u.lastLoginAt].map(esc).join(','));
  const blob = new Blob(['﻿' + [head.join(','), ...body].join('\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `linkrag-users-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** 设计稿 B4 用户列表：搜索 + 角色 / 状态筛选 + 排序 + 批量启用禁用 */
export function UserListView({ onTotal }: { onTotal?: (n: number) => void }) {
  const toast = useToast();
  const [keyword, setKeyword] = useState('');
  const [q, setQ] = useState('');
  const [role, setRole] = useState<RoleF>('all');
  const [status, setStatus] = useState<StatusF>('all');
  const [sort, setSort] = useState<'created' | 'lastLogin'>('created');
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<AdminUserDTO[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  // 输入防抖 300ms
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(keyword.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [keyword]);

  const reload = useCallback(() => {
    const id = ++seq.current;
    const query: UserQuery = { page, size: PAGE_SIZE, sort, keyword: q || undefined, role: role === 'all' ? undefined : role, status: status === 'all' ? undefined : (Number(status) as 0 | 1) };
    adminApi
      .users(query)
      .then((res) => {
        if (id !== seq.current) return;
        setRows(res.items);
        setTotal(res.total);
        setError(null);
        if (!q && role === 'all' && status === 'all') onTotal?.(res.total);
      })
      .catch((e: Error) => id === seq.current && setError(e.message || '加载失败'));
  }, [page, sort, q, role, status, onTotal]);
  useEffect(reload, [reload]);
  useEffect(() => setSelected(new Set()), [page, q, role, status]);

  const bulk = async (s: 0 | 1) => {
    setBusy(true);
    const ids = [...selected];
    const results = await Promise.allSettled(ids.map((id) => adminApi.setStatus(id, s)));
    const failed = results.filter((r): r is PromiseRejectedResult => r.status === 'rejected');
    setBusy(false);
    if (failed.length) toast(`${failed.length} 位用户操作失败：${(failed[0].reason as Error).message}`, { tone: 'error' });
    else toast(`已${s ? '启用' : '禁用'} ${ids.length} 位用户`, { tone: 'success' });
    setSelected(new Set());
    reload();
  };

  const allOn = !!rows?.length && rows.every((u) => selected.has(u.id));
  const toggleAll = () => setSelected(allOn ? new Set() : new Set(rows?.map((u) => u.id)));
  const toggle = (id: number) => setSelected((s) => (s.has(id) ? (s.delete(id), new Set(s)) : new Set(s.add(id))));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <SearchBox value={keyword} onChange={setKeyword} placeholder="搜索用户名、邮箱或 ID" className="w-[260px]" />
        <span className="text-[11.5px] text-muted">角色</span>
        <Segmented<RoleF> ariaLabel="角色" value={role} onChange={(v) => (setRole(v), setPage(1))} options={[{ value: 'all', label: '全部' }, { value: 'USER', label: '普通用户' }, { value: 'ADMIN', label: '管理员' }]} />
        <span className="text-[11.5px] text-muted">状态</span>
        <Segmented<StatusF> ariaLabel="状态" value={status} onChange={(v) => (setStatus(v), setPage(1))} options={[{ value: 'all', label: '全部' }, { value: '1', label: '启用' }, { value: '0', label: '禁用' }]} />
        <span className="ml-auto text-[11.5px] text-muted">排序</span>
        <Segmented ariaLabel="排序" value={sort} onChange={setSort} options={[{ value: 'created', label: '注册时间' }, { value: 'lastLogin', label: '最近登录' }]} />
        <button type="button" disabled={!rows?.length} onClick={() => rows && exportCsv(rows)} className={cn(actionBtn, 'flex items-center gap-1.5 font-normal disabled:opacity-50')}>
          <Download aria-hidden className="size-3.5" />
          导出 CSV
        </button>
      </div>

      {selected.size > 0 && (
        <div className="flex items-center gap-3 rounded-[10px] border border-line bg-soft px-4 py-2.5 text-[12px] text-ink">
          已选 {selected.size} 位用户
          <span className="flex-1" />
          <button type="button" disabled={busy} onClick={() => bulk(1)} className="rounded-[6px] border border-line bg-white px-3 py-1 text-text2 hover:bg-active disabled:opacity-50">
            启用
          </button>
          <button type="button" disabled={busy} onClick={() => bulk(0)} className="rounded-[6px] border border-line bg-white px-3 py-1 text-text2 hover:bg-active disabled:opacity-50">
            禁用
          </button>
          <button type="button" onClick={() => setSelected(new Set())} className="px-2 py-1 text-muted hover:text-ink">
            取消
          </button>
        </div>
      )}

      {rows && error && <StaleBanner message={`加载失败：${error}`} onRetry={reload} />}
      {!rows ? (
        error ? (
          <StateFeedback kind="error" title="用户列表加载失败" desc={error} action={<button type="button" onClick={reload} className={actionBtn}>重新加载</button>} />
        ) : (
          <StateFeedback kind="loading" title="正在加载" />
        )
      ) : !rows.length ? (
        <StateFeedback kind="empty" title={q || role !== 'all' || status !== 'all' ? '没有匹配的用户' : '还没有用户'} desc={q ? `没有找到与「${q}」相关的用户，换个关键字试试。` : undefined} />
      ) : (
        <div>
          <table className="w-full table-fixed">
            <thead className="border-b border-divider">
              <tr>
                <th className={cn(th, 'w-8')}>
                  <input type="checkbox" aria-label="全选当前页" checked={allOn} onChange={toggleAll} className="accent-ink" />
                </th>
                <th className={th}>用户</th>
                <th className={cn(th, 'w-[92px]')}>角色</th>
                <th className={cn(th, 'w-[74px]')}>状态</th>
                <th className={cn(th, 'w-[64px] text-right')}>知识库</th>
                <th className={cn(th, 'w-[104px] text-right')}>近 30 天 Token</th>
                <th className={cn(th, 'w-[104px] pl-6')}>注册时间</th>
                <th className={cn(th, 'w-[104px]')}>最近登录</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-divider border-b border-divider">
              {rows.map((u) => {
                const name = u.nickname?.trim() || u.username;
                return (
                  <tr key={u.id} className={cn('transition-colors hover:bg-soft/60', selected.has(u.id) && 'bg-soft/60')}>
                    <td className={td}>
                      <input type="checkbox" aria-label={`选择 ${name}`} checked={selected.has(u.id)} onChange={() => toggle(u.id)} className="accent-ink" />
                    </td>
                    <td className={td}>
                      <Link to={`/admin/users/${u.id}`} className="flex min-w-0 items-center gap-2.5">
                        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-active text-[11.5px] font-medium text-ink">{name.slice(0, 1).toUpperCase()}</span>
                        <span className="flex min-w-0 flex-col gap-0.5">
                          <span className="flex items-baseline gap-1.5">
                            <span className="truncate text-[12.5px] font-medium text-ink hover:underline">{name}</span>
                            <span className="font-num text-[10.5px] text-muted">#{u.id}</span>
                          </span>
                          <span className="truncate font-num text-[11px] text-muted">{u.email ?? u.username}</span>
                        </span>
                      </Link>
                    </td>
                    <td className={td}>{u.role === 'ADMIN' ? <Chip tone="blue" dot={false}>管理员</Chip> : <span className="text-text2">普通用户</span>}</td>
                    <td className={td}>{u.status ? <Chip tone="green">启用</Chip> : <Chip tone="gray">禁用</Chip>}</td>
                    <td className={cn(td, 'text-right font-num')}>{fmt(u.datasetCount)}</td>
                    <td className={cn(td, 'text-right font-num')}>{compact(u.tokens30d)}</td>
                    <td className={cn(td, 'pl-6 font-num text-[11.5px]')}>{u.createdAt?.slice(0, 10) ?? '—'}</td>
                    <td className={cn(td, 'font-num text-[11.5px]')}>{u.lastLoginAt ? relTime(u.lastLoginAt) : <span className="text-muted">从未登录</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <Pagination page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} />
        </div>
      )}
    </div>
  );
}
