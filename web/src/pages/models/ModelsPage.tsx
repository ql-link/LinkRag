import { Plus } from 'lucide-react';
import { useRef, useState } from 'react';

import { PageHeader } from '@/components/PageHeader';
import { SectionLabel } from '@/components/SectionLabel';
import { Button } from '@/components/ui/Button';
import { SearchBox } from '@/components/ui/SearchBox';
import { PageColumn } from '@/layouts/AppLayout';
import { CAPABILITIES } from '@/mock/models';
import { saveOnboarding } from '@/services/home';
import { stats, useModels } from '@/services/models';

import { DefaultModelCard } from './components/DefaultModelCard';
import { ProviderFlow } from './components/ProviderDialogs';
import { ProviderGroup } from './components/ProviderGroup';

/** D1 模型配置：默认模型（6 项能力）+ 按厂商分组的模型管理；D2/D3 接入厂商，D4 切换默认模型 */
export default function ModelsPage() {
  const providers = useModels((s) => s.providers);
  const models = useModels((s) => s.models);
  const count = useModels((s) => stats(s));
  const [query, setQuery] = useState('');
  const [flow, setFlow] = useState<{ edit?: string } | null>(null);
  const manageRef = useRef<HTMLDivElement>(null);

  const closeFlow = () => {
    setFlow(null);
    // 新用户引导第 1 步：接入任一厂商即视为完成
    if (providers.some((p) => !p.builtin && p.maskedKey)) saveOnboarding({ modelReady: true });
  };

  const q = query.trim();
  const groups = providers.map((p) => ({ provider: p, models: models.filter((m) => m.providerId === p.id) }));
  const hasMatch = !q || groups.some(({ provider, models: ms }) => provider.name.toLowerCase().includes(q.toLowerCase()) || ms.some((m) => m.name.toLowerCase().includes(q.toLowerCase())));

  return (
    <PageColumn>
      <PageHeader
        eyebrow="设置 · 模型配置"
        title="模型配置"
        description="设置各能力的默认模型，并管理已接入的模型厂商。"
        actions={
          <>
            <SearchBox value={query} onChange={setQuery} placeholder="搜索厂商、模型或能力" className="w-[220px]" />
            <Button icon={<Plus className="size-3" />} onClick={() => setFlow({})}>
              添加厂商
            </Button>
          </>
        }
      />

      <SectionLabel label="默认模型" action={<span className="text-muted">{CAPABILITIES.length} 项能力</span>} className="mb-[18px]" />
      <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3">
        {CAPABILITIES.map((cap) => (
          <DefaultModelCard key={cap} cap={cap} onAddProvider={() => setFlow({})} onManage={() => manageRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })} />
        ))}
      </div>

      <div ref={manageRef} className="scroll-mt-6">
        <SectionLabel label="模型管理" action={<span className="text-muted">{count.providers} 个厂商 · {count.models} 个模型</span>} className="mt-[30px] mb-[18px]" />
      </div>
      <div className="flex flex-col gap-3">
        {groups.map(({ provider, models: ms }) => (
          <ProviderGroup key={provider.id} provider={provider} models={ms} query={q} onEdit={() => setFlow({ edit: provider.id })} />
        ))}
        {!hasMatch && (
          <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-dash py-10 text-[12.5px] text-muted">
            没有匹配「{q}」的厂商或模型
            <button type="button" onClick={() => setFlow({})} className="text-ink underline-offset-2 hover:underline">
              添加新的模型厂商
            </button>
          </div>
        )}
      </div>

      {flow && <ProviderFlow editProviderId={flow.edit} onClose={closeFlow} />}
    </PageColumn>
  );
}
