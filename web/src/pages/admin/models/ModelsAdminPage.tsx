/** 管理台 · 模型管理：目录（D1）/ 候选审核（D2）/ 平台配置（D3），弹窗 D4–D9 */
import { History, Plus } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { Button } from '@/components/ui/Button';
import { SearchBox } from '@/components/ui/SearchBox';

import { AdminColumn } from '../AdminLayout';
import { AdminHeader, UnderlineTabs } from '../ui';
import { CandidatesTab } from './CandidatesTab';
import { CatalogTab } from './CatalogTab';
import { PlatformTab } from './PlatformTab';

type Tab = 'catalog' | 'candidates' | 'platform';
const TABS: { value: Tab; label: string }[] = [
  { value: 'catalog', label: '厂商 · 模型能力目录' },
  { value: 'candidates', label: '外部模型候选' },
  { value: 'platform', label: 'LinkRag 平台模型' },
];

export default function ModelsAdminPage() {
  const [params, setParams] = useSearchParams();
  const raw = params.get('tab');
  const tab: Tab = raw === 'candidates' || raw === 'platform' ? raw : 'catalog';
  const historyOpen = tab === 'catalog' && params.get('sync') === 'history';
  const providerParam = Number(params.get('provider'));
  const providerId = Number.isFinite(providerParam) && providerParam > 0 ? providerParam : null;
  const [query, setQuery] = useState('');
  const [addProvider, setAddProvider] = useState(0);
  const [addPlatform, setAddPlatform] = useState(0);

  const go = (next: Record<string, string | null>) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p);
        for (const [k, v] of Object.entries(next)) {
          if (v === null) n.delete(k);
          else n.set(k, v);
        }
        return n;
      },
      { replace: false },
    );

  return (
    <AdminColumn fill={tab === 'catalog'}>
      <AdminHeader
        eyebrow="管理台 · 模型"
        title="模型管理"
        desc="维护厂商与模型能力目录、审核外部同步候选，并配置全站共享的平台模型。"
        actions={
          <>
            <SearchBox value={query} onChange={setQuery} placeholder="搜索厂商、模型或密钥" className="w-[240px]" />
            <Button variant="secondary" icon={<History className="size-3.5" />} onClick={() => go({ tab: 'catalog', sync: 'history' })}>
              同步历史
            </Button>
            {tab === 'platform' ? (
              <Button icon={<Plus className="size-3.5" />} onClick={() => setAddPlatform((n) => n + 1)}>
                添加平台模型
              </Button>
            ) : (
              <Button
                icon={<Plus className="size-3.5" />}
                onClick={() => {
                  if (tab !== 'catalog') go({ tab: 'catalog' });
                  setAddProvider((n) => n + 1);
                }}
              >
                新增厂商
              </Button>
            )}
          </>
        }
        tabs={<UnderlineTabs label="模型管理视图" items={TABS} value={tab} onChange={(v) => {
              setAddProvider(0);
              go({ tab: v, sync: null });
            }} />}
      />
      {tab === 'catalog' && (
        <CatalogTab
          query={query}
          historyOpen={historyOpen}
          onHistory={(open) => go({ sync: open ? 'history' : null })}
          addProviderSignal={addProvider}
        />
      )}
      {tab === 'candidates' && <CandidatesTab query={query} providerId={providerId} onProvider={(id) => go({ provider: id === null ? null : String(id) })} />}
      {tab === 'platform' && <PlatformTab query={query} addSignal={addPlatform} />}
    </AdminColumn>
  );
}
