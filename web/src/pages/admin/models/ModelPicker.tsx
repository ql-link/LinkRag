/** D6「从已上架模型添加」：来源厂商 / 能力筛选 + 单选列表 */
import { cn } from '@/lib/cn';

import { StateFeedback } from '../StateFeedback';
import { CAPABILITIES, CAPABILITY_LABEL, type Capability, type Provider, type ProviderModel } from './api';
import { ProviderAvatar, selectCls } from './shared';

interface Props {
  providers: Provider[];
  models: ProviderModel[];
  provider: string;
  onProvider: (v: string) => void;
  capability: Capability;
  onCapability: (v: Capability) => void;
  picked: number | null;
  onPick: (id: number) => void;
}

export function ModelPicker({ providers, models, provider, onProvider, capability, onCapability, picked, onPick }: Props) {
  const byId = new Map(providers.map((p) => [p.id, p]));
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-4">
        <label className="flex flex-col gap-[7px] text-[12px] font-medium text-ink">
          来源厂商
          <select className={selectCls} value={provider} onChange={(e) => onProvider(e.target.value)}>
            <option value="">全部厂商</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.providerName}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-[7px] text-[12px] font-medium text-ink">
          来源能力
          <select className={selectCls} value={capability} onChange={(e) => onCapability(e.target.value as Capability)}>
            {CAPABILITIES.map((c) => (
              <option key={c} value={c}>
                {CAPABILITY_LABEL[c]} {c}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-[12px] font-medium text-ink">已上架正式模型</p>
      {models.length === 0 ? (
        <StateFeedback kind="empty" size="inline" title="没有符合条件的已上架模型" />
      ) : (
        <ul role="radiogroup" aria-label="已上架正式模型" className="flex max-h-[220px] flex-col gap-1.5 overflow-y-auto">
          {models.map((m) => {
            const p = byId.get(m.providerId);
            const on = picked === m.id;
            return (
              <li key={m.id}>
                <button
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => onPick(m.id)}
                  className={cn('flex w-full items-center gap-3 rounded-[10px] border px-3 py-2 text-left transition-colors', on ? 'border-ink bg-soft' : 'border-line hover:bg-soft/60')}
                >
                  <ProviderAvatar name={p?.providerName ?? '?'} iconUrl={p?.iconUrl} type={p?.providerType} size={24} />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-[12.5px] font-medium text-ink">{m.displayName || m.modelName}</span>
                    <span className="truncate font-num text-[11px] text-muted">
                      {p?.providerType} · {m.modelName}
                    </span>
                  </span>
                  <span className="text-[11.5px] text-muted">{p?.providerName}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
