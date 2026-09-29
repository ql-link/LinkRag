import { ChevronDown, KeyRound, MoreHorizontal, Pencil, Trash2 } from 'lucide-react';
import { useId, useState } from 'react';

import { ProviderMark } from '@/components/ProviderMark';
import { Chip } from '@/components/ui/Chip';
import { Menu } from '@/components/ui/Menu';
import { Switch } from '@/components/ui/Switch';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import { capabilityLabel } from '@/mock/models';
import { defaultUsages, removeProvider, toggleModel, useModels } from '@/services/models';
import type { ModelInfo, Provider } from '@/types';

interface Props {
  provider: Provider;
  models: ModelInfo[];
  query: string;
  onEdit: () => void;
}

/** D1 模型管理：一个厂商一张卡片，默认折叠只显示头部摘要；展开后逐行列出模型与启用开关（D5） */
export function ProviderGroup({ provider, models, query, onEdit }: Props) {
  const toast = useToast();
  const defaults = useModels((s) => s.defaults);
  const [expanded, setExpanded] = useState(false);
  const listId = useId();
  const q = query.trim().toLowerCase();
  const visible = q && !provider.name.toLowerCase().includes(q) ? models.filter((m) => m.name.toLowerCase().includes(q) || m.capabilities.some((c) => capabilityLabel[c].includes(q))) : models;
  if (q && !visible.length) return null;
  // 搜索时自动展开命中的厂商
  const open = expanded || !!q;
  const enabledCount = models.filter((m) => m.enabled).length;
  const toggleOpen = () => setExpanded((v) => !v);

  const toggle = (m: ModelInfo, on: boolean) => {
    try {
      toggleModel(m.id, on);
      toast(`${m.name} 已${on ? '启用' : '停用'}`);
    } catch (e) {
      toast((e as Error).message, { tone: 'error' });
    }
  };
  const remove = () => {
    try {
      removeProvider(provider.id);
      toast(`已移除 ${provider.name}`, { tone: 'success' });
    } catch (e) {
      toast((e as Error).message, { tone: 'error' });
    }
  };

  return (
    <section aria-label={provider.name} className="flex flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-card">
      <header onClick={toggleOpen} className="flex cursor-pointer items-center gap-3 px-[18px] py-3.5 select-none">
        <ProviderMark letter={provider.letter} color={provider.color} iconUrl={provider.iconUrl} size={28} />
        <h3 className="text-[13.5px] font-medium text-ink">{provider.name}</h3>
        {provider.builtin ? <Chip tone="gray">平台内置</Chip> : <Chip tone="green">已配置</Chip>}
        <span className="text-[11px] text-muted">
          {models.length} 个模型 · {enabledCount} 个已启用
        </span>
        <span className="flex-1" />
        {provider.builtin ? (
          <span className="text-[11px] text-muted">无需密钥 · 含免费额度</span>
        ) : (
          <>
            <span className="flex items-center gap-1.5 font-num text-[11px] font-medium text-muted">
              <KeyRound aria-hidden className="size-3" />
              {provider.maskedKey}
            </span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onEdit();
              }}
              className="text-[11.5px] text-text2 hover:text-ink"
            >
              更新密钥
            </button>
          </>
        )}
        <button
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          aria-label={`${open ? '收起' : '展开'} ${provider.name} 的模型`}
          onClick={(e) => {
            e.stopPropagation();
            toggleOpen();
          }}
          className="-mr-1 rounded p-1 text-muted hover:bg-soft hover:text-ink"
        >
          <ChevronDown aria-hidden className={cn('size-[13px] transition-transform', open && 'rotate-180')} />
        </button>
      </header>
      {open && <div className="h-px bg-divider" />}
      <ul id={listId} hidden={!open} className="pb-1">
        {visible.map((m) => {
          const usedAs = defaultUsages(m.id, { providers: [], models: [], defaults });
          return (
            <li key={m.id} className="flex items-center gap-3 py-2.5 pr-[18px] pl-[58px]">
              <span className="font-num text-[12.5px] font-medium text-ink">{m.name}</span>
              <span className="text-[11px] text-muted">{[...m.capabilities.map((c) => capabilityLabel[c]), m.tag === '推理' ? '推理' : null].filter(Boolean).join(' · ')}</span>
              {usedAs.length > 0 && (
                <span className="rounded-[5px] bg-ink/[0.06] px-1.5 py-0.5 text-[10px] leading-none font-medium text-text2">默认 · {usedAs.map((c) => capabilityLabel[c]).join('、')}</span>
              )}
              <span className="flex-1" />
              <span className={m.enabled ? 'text-[11px] text-text2' : 'text-[11px] text-muted'}>{m.enabled ? '已启用' : '已停用'}</span>
              <Switch checked={m.enabled} onChange={(v) => toggle(m, v)} label={`${m.enabled ? '停用' : '启用'} ${m.name}`} />
              {provider.builtin ? (
                <span className="size-3.5" />
              ) : (
                <Menu
                  width={160}
                  items={[
                    { key: 'edit', label: '编辑厂商配置', icon: <Pencil />, onSelect: onEdit },
                    { key: 'remove', label: `移除 ${provider.name}`, icon: <Trash2 />, danger: true, divider: true, onSelect: remove },
                  ]}
                  trigger={({ toggle: t }) => (
                    <button type="button" onClick={t} aria-label={`${m.name} 更多操作`} className="rounded p-0.5 text-muted hover:bg-soft hover:text-ink">
                      <MoreHorizontal className="size-3.5" />
                    </button>
                  )}
                />
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
