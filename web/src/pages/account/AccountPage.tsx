import { ChevronRight, KeyRound, LogOut } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

import { PageHeader } from '@/components/PageHeader';
import { SectionLabel } from '@/components/SectionLabel';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Field, TextArea, TextInput } from '@/components/ui/Field';
import { AuthError, useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/contexts/ToastContext';
import { PageColumn } from '@/layouts/AppLayout';

const NAME_MAX = 20;
const BIO_MAX = 120;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface Draft {
  displayName: string;
  email: string;
  team: string;
  bio: string;
}

/** 用户信息管理：点击侧栏头像进入；个人资料可直接编辑保存，密码通过弹窗修改 */
export default function AccountPage() {
  const { user, updateProfile, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const initial: Draft = { displayName: user?.displayName ?? '', email: user?.email ?? '', team: user?.team ?? '', bio: user?.bio ?? '' };
  const [draft, setDraft] = useState<Draft>(initial);
  const [saving, setSaving] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  if (!user) return null;

  const errors = {
    displayName: !draft.displayName.trim() ? '请输入显示名称' : undefined,
    email: !EMAIL_RE.test(draft.email.trim()) ? '邮箱格式不正确' : undefined,
  };
  const dirty = (Object.keys(initial) as (keyof Draft)[]).some((k) => draft[k].trim() !== initial[k]);
  const valid = !errors.displayName && !errors.email;
  const set = (k: keyof Draft) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [k]: e.target.value }));

  const save = async () => {
    setSaving(true);
    await updateProfile({ displayName: draft.displayName.trim(), email: draft.email.trim(), team: draft.team.trim(), bio: draft.bio.trim() });
    setSaving(false);
    toast('个人资料已保存', { tone: 'success' });
  };

  return (
    <PageColumn>
      <PageHeader eyebrow="账号" title="用户信息" description="管理个人资料与登录安全。" />

      <SectionLabel label="个人资料" className="mb-3" />
      <div className="flex items-center gap-4 border-t border-divider pt-4">
        <span aria-hidden className="flex size-[52px] shrink-0 items-center justify-center rounded-full bg-ink text-[20px] font-medium text-white">
          {(draft.displayName.trim() || user.username).slice(0, 1).toUpperCase()}
        </span>
        <div className="flex min-w-0 flex-col gap-1">
          <span className="truncate text-[17px] font-semibold text-ink">{draft.displayName.trim() || user.username}</span>
          <span className="truncate text-[12px] text-muted">
            @{user.username}
            {user.createdAt && ` · 注册于 ${user.createdAt}`}
          </span>
        </div>
      </div>

      <form
        aria-label="个人资料"
        className="mt-6 grid grid-cols-2 gap-x-6 gap-y-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (dirty && valid && !saving) void save();
        }}
      >
        <Field label="显示名称" required error={errors.displayName} hint="显示在侧栏与对话中">
          {(id, d) => <TextInput id={id} aria-describedby={d} invalid={!!errors.displayName} maxLength={NAME_MAX} value={draft.displayName} onChange={set('displayName')} />}
        </Field>
        <Field label="用户名" hint="用于登录，注册后不可修改">
          {(id, d) => <TextInput id={id} aria-describedby={d} value={user.username} readOnly disabled className="bg-soft" />}
        </Field>
        <Field label="邮箱" required error={errors.email}>
          {(id, d) => <TextInput id={id} type="email" aria-describedby={d} invalid={!!errors.email} value={draft.email} onChange={set('email')} />}
        </Field>
        <Field label="所属团队">
          {(id) => <TextInput id={id} placeholder="例如：产品研发部" maxLength={30} value={draft.team} onChange={set('team')} />}
        </Field>
        <div className="col-span-2">
          <Field label="个人简介" hint={`${draft.bio.length} / ${BIO_MAX}`}>
            {(id, d) => <TextArea id={id} aria-describedby={d} placeholder="介绍一下你的职责或关注的领域" maxLength={BIO_MAX} value={draft.bio} onChange={set('bio')} />}
          </Field>
        </div>
        <div className="col-span-2 flex justify-end gap-2.5">
          <Button variant="secondary" disabled={!dirty || saving} onClick={() => setDraft(initial)}>
            撤销修改
          </Button>
          <Button type="submit" disabled={!dirty || !valid || saving}>
            {saving ? '保存中…' : '保存修改'}
          </Button>
        </div>
      </form>

      <SectionLabel label="账号与安全" className="mt-10 mb-3" />
      <ul className="border-t border-divider">
        <Row label="登录邮箱" value={user.email} />
        <Row
          label="登录密码"
          value="建议定期更换，至少 8 位"
          action={
            <button type="button" onClick={() => setPasswordOpen(true)} className="flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-text2 hover:bg-soft hover:text-ink">
              <KeyRound aria-hidden className="size-3" />
              修改密码
              <ChevronRight aria-hidden className="size-3" />
            </button>
          }
        />
      </ul>

      <div className="mt-8 flex">
        <button
          type="button"
          onClick={() => {
            logout();
            navigate('/login');
          }}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[12.5px] font-medium text-red hover:bg-red/5"
        >
          <LogOut aria-hidden className="size-3.5" />
          退出登录
        </button>
      </div>

      <PasswordDialog open={passwordOpen} onClose={() => setPasswordOpen(false)} />
    </PageColumn>
  );
}

function Row({ label, value, action }: { label: string; value: string; action?: ReactNode }) {
  return (
    <li className="flex h-12 items-center gap-4 border-b border-divider">
      <span className="w-[180px] shrink-0 text-[13.5px] font-medium text-ink">{label}</span>
      <span className="min-w-0 flex-1 truncate text-[12.5px] text-text2">{value}</span>
      {action}
    </li>
  );
}

function PasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { changePassword } = useAuth();
  const toast = useToast();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<AuthError | null>(null);
  const [busy, setBusy] = useState(false);

  const close = () => {
    setCurrent('');
    setNext('');
    setConfirm('');
    setError(null);
    onClose();
  };
  const nextError = next && next.length < 8 ? '新密码至少 8 位' : error?.field === 'password' ? error.message : undefined;
  const confirmError = confirm && confirm !== next ? '两次输入的密码不一致' : undefined;
  const ready = current && next.length >= 8 && confirm === next && !busy;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await changePassword(current, next);
      toast('密码已修改', { tone: 'success' });
      close();
    } catch (e) {
      if (e instanceof AuthError) setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="修改登录密码"
      description="修改后，其他设备上的登录状态将失效。"
      width={440}
      footer={
        <>
          <Button variant="secondary" onClick={close}>
            取消
          </Button>
          <Button disabled={!ready} onClick={() => void submit()}>
            {busy ? '提交中…' : '确认修改'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field label="当前密码" required error={error?.field === 'current' ? error.message : undefined}>
          {(id, d) => <TextInput id={id} type="password" autoComplete="current-password" aria-describedby={d} invalid={error?.field === 'current'} value={current} onChange={(e) => setCurrent(e.target.value)} />}
        </Field>
        <Field label="新密码" required error={nextError}>
          {(id, d) => <TextInput id={id} type="password" autoComplete="new-password" aria-describedby={d} invalid={!!nextError} value={next} onChange={(e) => setNext(e.target.value)} />}
        </Field>
        <Field label="确认新密码" required error={confirmError}>
          {(id, d) => <TextInput id={id} type="password" autoComplete="new-password" aria-describedby={d} invalid={!!confirmError} value={confirm} onChange={(e) => setConfirm(e.target.value)} />}
        </Field>
      </div>
    </Dialog>
  );
}
