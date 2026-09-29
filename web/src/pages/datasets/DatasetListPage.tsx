import { ArrowDownUp, Database, Plus } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { PageHeader } from '@/components/PageHeader';
import { Button } from '@/components/ui/Button';
import { Menu } from '@/components/ui/Menu';
import { SearchBox } from '@/components/ui/SearchBox';
import { PageColumn } from '@/layouts/AppLayout';
import { fileCount } from '@/services/datasets';
import { useStore } from '@/services/useStore';

import { CreateDatasetDialog } from './components/CreateDatasetDialog';
import { useDatasetActions } from './components/DatasetActions';
import { DatasetCard } from './components/DatasetCard';

type SortKey = 'updated' | 'name' | 'files';
const sortLabel: Record<SortKey, string> = { updated: '按更新时间', name: '按名称', files: '按文件数' };

/** C1 知识库列表 / C2 空态 */
export default function DatasetListPage() {
  const datasets = useStore((s) => s.datasets);
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<SortKey>('updated');
  const [creating, setCreating] = useState(false);
  const actions = useDatasetActions({ afterDelete: () => {} });

  const totalFiles = datasets.reduce((n, d) => n + fileCount(d.id), 0);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = datasets.filter((d) => !q || d.name.toLowerCase().includes(q) || d.description.toLowerCase().includes(q));
    if (sort === 'name') return [...list].sort((a, b) => a.name.localeCompare(b.name, 'zh'));
    if (sort === 'files') return [...list].sort((a, b) => fileCount(b.id) - fileCount(a.id));
    return list;
  }, [datasets, query, sort]);

  const empty = datasets.length === 0;
  const createButton = (
    <Button icon={<Plus className="size-3" />} onClick={() => setCreating(true)}>
      新建知识库
    </Button>
  );

  return (
    <PageColumn>
      <PageHeader
        eyebrow={empty ? '知识库 · 0 个' : `知识库 · ${datasets.length} 个 · 共 ${totalFiles.toLocaleString('en-US')} 个文件`}
        title="知识库"
        description="上传文档、配置解析方式，然后在对话中检索问答。"
        actions={
          empty ? (
            createButton
          ) : (
            <>
              <SearchBox value={query} onChange={setQuery} placeholder="搜索知识库..." className="w-[180px]" />
              <Menu
                width={140}
                items={(Object.keys(sortLabel) as SortKey[]).map((k) => ({ key: k, label: sortLabel[k], onSelect: () => setSort(k) }))}
                trigger={({ toggle }) => (
                  <Button variant="secondary" icon={<ArrowDownUp className="size-3" />} onClick={toggle}>
                    {sortLabel[sort]}
                  </Button>
                )}
              />
              {createButton}
            </>
          )
        }
      />

      {empty ? (
        <div className="flex flex-col items-center gap-2.5 rounded-2xl border border-dashed border-dash py-12">
          <span className="flex size-11 items-center justify-center rounded-full bg-soft">
            <Database aria-hidden className="size-[18px] text-text2" />
          </span>
          <p className="text-[14px] font-medium text-ink">还没有知识库</p>
          <p className="text-[12px] text-muted">新建一个知识库后，就可以上传文件并开始问答</p>
          <div className="mt-1.5">{createButton}</div>
        </div>
      ) : visible.length === 0 ? (
        <p className="py-16 text-center text-[12.5px] text-muted">没有找到与「{query}」匹配的知识库</p>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-4">
          {visible.map((ds) => (
            <DatasetCard key={ds.id} dataset={ds} onAction={(a, d) => (a === 'enable' ? actions.enable(d) : actions.open(a, d))} />
          ))}
        </div>
      )}

      <CreateDatasetDialog open={creating} onClose={() => setCreating(false)} onCreated={(ds) => navigate(`/datasets/${ds.id}`)} />
      {actions.dialogs}
    </PageColumn>
  );
}
