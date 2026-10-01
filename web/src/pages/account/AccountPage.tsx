import { KeyRound, LogOut } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import cameraIcon from '@/assets/account/camera.svg';
import shieldIcon from '@/assets/account/shield.svg';
import { AvatarDialog } from '@/components/AvatarDialog';
import { UserAvatar } from '@/components/UserAvatar';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Field, TextArea, TextInput } from '@/components/ui/Field';
import { AuthError, useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/contexts/ToastContext';

const NAME_MAX = 20;
const BIO_MAX = 120;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface Draft {
  displayName: string;
  email: string;
  team: string;
  bio: string;
}

/** 账户资料与登录安全；头像和密码使用独立弹窗编辑。 */
export default function AccountPage() {
  const { user, updateProfile, logout } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const initial: Draft = { displayName: user?.displayName ?? '', email: user?.email ?? '', team: user?.team ?? '', bio: user?.bio ?? '' };
  const [draft, setDraft] = useState<Draft>(initial);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [avatarOpen, setAvatarOpen] = useState(false);
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
    setSaveError(null);
    try {
      await updateProfile({ displayName: draft.displayName.trim(), email: draft.email.trim(), team: draft.team.trim(), bio: draft.bio.trim() });
      toast('个人资料已保存', { tone: 'success' });
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : '保存失败，请稍后重试');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-[976px] px-6 pt-10 pb-16 font-sans">
      <header className="mb-6">
        <h1 className="text-[28px] leading-10 font-medium text-ink">用户信息</h1>
        <p className="mt-1 text-[13px] leading-5 text-account-muted">管理个人资料与登录安全。</p>
      </header>

      <section aria-label="账户概览" className="flex min-h-[92px] items-center gap-4 rounded-xl border border-account-line bg-white p-[18px]">
        <button type="button" aria-label="修改头像" onClick={() => setAvatarOpen(true)} className="relative shrink-0 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ink focus-visible:ring-offset-2">
          <UserAvatar user={user} className="size-14 text-[20px]" />
          <span className="absolute -right-1 -bottom-1 flex size-6 items-center justify-center rounded-full border border-account-line bg-white">
            <img src={cameraIcon} alt="" className="size-3.5" />
          </span>
        </button>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="truncate text-[17px] leading-6 font-medium text-ink">{user.displayName || user.username}</span>
          <span className="truncate text-[12px] leading-[18px] text-account-muted">@{user.username}</span>
        </div>
        {user.createdAt && <p className="text-right text-[12px] leading-5 text-account-muted">注册于 {user.createdAt}</p>}
      </section>

      {/* 两列通过 grid stretch 保持等高，错误提示展开时不依赖测量。 */}
      <div className="mt-6 grid items-stretch gap-6 md:grid-cols-[minmax(0,584fr)_minmax(0,320fr)]">
        <form
          aria-label="个人资料"
          className="flex min-h-[572px] min-w-0 flex-col rounded-xl border border-account-line bg-white p-6"
          onSubmit={(e) => {
            e.preventDefault();
            if (dirty && valid && !saving) void save();
          }}
        >
          <h2 className="text-[17px] leading-6 font-medium text-ink">个人资料</h2>
          <p className="mt-1 text-[12px] leading-5 text-account-muted">完善你的资料，让协作更高效</p>
          <div className="mt-6 grid grid-cols-1 gap-x-4 gap-y-5 sm:grid-cols-2">
            <Field label="显示名称" required error={errors.displayName} hint="显示在侧栏与对话中">
              {(id, d) => <TextInput id={id} aria-describedby={d} invalid={!!errors.displayName} maxLength={NAME_MAX} value={draft.displayName} onChange={set('displayName')} className={`h-11 bg-account-soft ${errors.displayName ? '' : 'border-account-line'}`} />}
            </Field>
            <Field label="用户名" hint="用于登录，注册后不可修改">
              {(id, d) => <TextInput id={id} aria-describedby={d} value={user.username} readOnly disabled className="h-11 border-account-line bg-account-soft [&_input]:text-account-muted" />}
            </Field>
            <Field label="邮箱" required error={errors.email}>
              {(id, d) => <TextInput id={id} type="email" aria-describedby={d} invalid={!!errors.email} value={draft.email} onChange={set('email')} className={`h-11 bg-account-soft ${errors.email ? '' : 'border-account-line'}`} />}
            </Field>
            <Field label="所属团队">
              {(id) => <TextInput id={id} placeholder="例如：产品研发部" maxLength={30} value={draft.team} onChange={set('team')} className="h-11 border-account-line bg-account-soft" />}
            </Field>
            <div className="sm:col-span-2 [&_p]:text-right">
              <Field label="个人简介" hint={`${draft.bio.length} / ${BIO_MAX}`}>
                {(id, d) => <TextArea id={id} aria-describedby={d} placeholder="介绍一下你的职责或关注的领域" maxLength={BIO_MAX} value={draft.bio} onChange={set('bio')} className="h-[125px] border-account-line bg-account-soft" />}
              </Field>
            </div>
          </div>
          <div className="mt-auto pt-6">
            {saveError && <p role="alert" className="mb-3 text-[12px] text-account-danger">{saveError}</p>}
            <div className="flex justify-end gap-2.5 border-t border-account-line pt-5">
              <Button variant="secondary" className="h-10 rounded-lg border-account-line" disabled={!dirty || saving} onClick={() => { setDraft(initial); setSaveError(null); }}>
                撤销修改
              </Button>
              <Button type="submit" className="h-10 rounded-lg disabled:bg-account-disabled disabled:text-account-muted disabled:opacity-100" disabled={!dirty || !valid || saving}>
                {saving ? '保存中…' : '保存修改'}
              </Button>
            </div>
          </div>
        </form>

        <div className="flex min-w-0 flex-col gap-4">
          <section aria-labelledby="account-security-title" className="flex flex-1 flex-col rounded-xl border border-account-line bg-white p-6">
            <h2 id="account-security-title" className="flex items-center gap-2 text-[17px] leading-6 font-medium text-ink">
              <img src={shieldIcon} alt="" className="size-[18px]" />
              账号与安全
            </h2>
            <div className="mt-6 border-b border-account-line pb-5">
              <p className="text-[12px] font-medium text-ink">登录邮箱</p>
              <p className="mt-2 break-all text-[13px] leading-5 text-account-muted">{user.email}</p>
            </div>
            <div className="pt-5">
              <p className="text-[12px] font-medium text-ink">登录密码</p>
              <p className="mt-2 text-[12px] leading-5 text-account-muted">建议定期更换，至少 8 位</p>
              <Button variant="secondary" block className="mt-4 h-10 rounded-lg border-account-line" onClick={() => setPasswordOpen(true)} icon={<KeyRound aria-hidden className="size-3.5" />}>
                修改密码
              </Button>
            </div>
            <div className="mt-auto pt-6">
              <p className="rounded-lg bg-account-soft p-3 text-[12px] leading-5 text-account-muted">安全提示：请勿与他人共享密码，定期更新密码以保护你的账号安全。</p>
            </div>
          </section>

          <section aria-labelledby="account-logout-title" className="flex min-h-[152px] flex-col rounded-xl border border-account-line bg-white p-6">
            <h2 id="account-logout-title" className="text-[15px] leading-5 font-medium text-ink">退出当前账号</h2>
            <p className="mt-1 text-[12px] leading-5 text-account-muted">退出后需要重新登录才能继续使用。</p>
            <Button
              variant="secondary"
              block
              className="mt-4 h-10 rounded-lg border-account-line text-account-danger hover:bg-account-danger/5"
              icon={<LogOut aria-hidden className="size-3.5" />}
              onClick={() => {
                logout();
                navigate('/login');
              }}
            >
              退出登录
            </Button>
          </section>
        </div>
      </div>

      <AvatarDialog open={avatarOpen} onClose={() => setAvatarOpen(false)} />
      <PasswordDialog open={passwordOpen} onClose={() => setPasswordOpen(false)} />
    </div>
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
