/** 模型管理页内共用的小组件 */
import type { ReactNode } from 'react';

import { Chip } from '@/components/ui/Chip';
import { ProviderMark } from '@/components/ProviderMark';
import { cn } from '@/lib/cn';
import { SYSTEM_LOGO } from '@/services/backend';

import { actionBtn, StaleBanner, StateFeedback } from '../StateFeedback';
import { CAPABILITY_LABEL, type Capability } from './api';

const COLORS = ['#10a37f', '#4d6bfe', '#ff6a00', '#3859ff', '#d97757', '#111827', '#e2372b', '#4285f4', '#7c3aed'];

/** 平台内置厂商（providerType=linkrag）与 LinkRag 平台模型统一使用随前端打包的系统 logo */
export const isSystemProvider = (type?: string | null) => type?.toLowerCase() === 'linkrag';

/** 厂商头像：优先加载 sys_provider 维护的 logo，系统厂商用系统 logo，加载失败回退首字母方块 */
export function ProviderAvatar({ name, iconUrl, type, system, size = 28 }: { name: string; iconUrl?: string | null; type?: string | null; system?: boolean; size?: number }) {
  const letter = (name.trim()[0] ?? '?').toUpperCase();
  const color = COLORS[[...name].reduce((s, c) => s + c.charCodeAt(0), 0) % COLORS.length];
  const src = system || isSystemProvider(type) ? SYSTEM_LOGO : (iconUrl ?? undefined);
  return <ProviderMark letter={letter} color={color} iconUrl={src} size={size} />;
}

export const CapChip = ({ cap }: { cap: Capability }) => (
  <Chip tone="gray" dot={false}>
    {CAPABILITY_LABEL[cap] ?? cap}
  </Chip>
);

export const ActiveChip = ({ on, onText = '启用', offText = '停用' }: { on: boolean; onText?: string; offText?: string }) => (
  <Chip tone={on ? 'green' : 'gray'}>{on ? onText : offText}</Chip>
);

/** 小号图标按钮（设计稿 Button/s 28x26） */
export function IconBtn({ label, onClick, children, danger, disabled }: { label: string; onClick: () => void; children: ReactNode; danger?: boolean; disabled?: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={cn('flex h-[26px] w-7 items-center justify-center rounded-[7px] border border-line bg-white text-text2 transition-colors hover:bg-soft disabled:opacity-40', danger && 'hover:text-red')}
    >
      {children}
    </button>
  );
}

/** 筛选胶囊 */
export function FilterChip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn('rounded-full border px-2.5 py-[3px] text-[12px] transition-colors', on ? 'border-transparent bg-active font-medium text-ink' : 'border-line bg-white text-text2 hover:bg-soft')}
    >
      {children}
    </button>
  );
}

/** 统一的加载 / 失败 / 刷新失败外壳 */
export function LoadGate<T>({ state, title, children, size = 'card' }: { state: { data: T | null; error: string | null; reload: () => void }; title: string; size?: 'page' | 'card'; children: (d: T) => ReactNode }) {
  const { data, error, reload } = state;
  if (data === null)
    return error ? (
      <StateFeedback kind="error" size={size} title={`${title}加载失败`} desc={error} action={<button type="button" onClick={reload} className={actionBtn}>重新加载</button>} />
    ) : (
      <StateFeedback kind="loading" size={size} title="正在加载" />
    );
  return (
    <>
      {error && <StaleBanner message={`刷新失败：${error}`} onRetry={reload} />}
      {children(data)}
    </>
  );
}

export const selectCls = 'h-10 w-full rounded-[10px] border border-line bg-white px-3 text-[13px] text-ink outline-none focus:border-ink';
