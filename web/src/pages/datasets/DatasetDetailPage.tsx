import { Power } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { Breadcrumb } from '@/components/Breadcrumb';
import { PageHeader } from '@/components/PageHeader';
import { PageLoading } from '@/components/ui/Loading';
import { Button } from '@/components/ui/Button';
import { Segmented } from '@/components/ui/Segmented';
import { SearchBox } from '@/components/ui/SearchBox';
import { useToast } from '@/contexts/ToastContext';
import { PageColumn } from '@/layouts/AppLayout';
import { cancelUploads, clearFailed, fileStats, parseAll, refreshFiles, updateDataset, uploadFiles } from '@/services/datasets';
import { useStore } from '@/services/useStore';
import { usePageLoad } from '@/lib/usePageLoad';
import type { KbFile } from '@/types';

import { useDatasetActions } from './components/DatasetActions';
import { FileRow } from './components/FileRow';
import { ParseSummaryCard } from './components/ParseSummaryCard';
import { Dropzone, MAX_SIZE, NextSteps, useFilePickers } from './components/UploadPanel';
import { UploadTray } from './components/UploadTray';

type Filter = 'all' | 'done' | 'running' | 'failed';

const matchFilter: Record<Filter, (f: KbFile) => boolean> = {
  all: () => true,
  done: (f) => f.status === 'done',
  running: (f) => f.status === 'uploading' || f.status === 'parsing' || f.status === 'queued',
  failed: (f) => f.status === 'failed',
};

/** C3 刚创建 / C4 文件列表 / C5 上传与解析中 */
export default function DatasetDetailPage() {
  const { datasetId = '' } = useParams();
  const toast = useToast();
  const dataset = useStore((s) => s.datasets.find((d) => d.id === datasetId));
  const files = useStore((s) => s.files.filter((f) => f.datasetId === datasetId));
  const stats = useStore(() => fileStats(datasetId));
  const actions = useDatasetActions();

  // 真实模式：进入详情时拉取文件、解析状态与模型绑定，全部返回后再展示（Mock 模式为 no-op）
  const loaded = usePageLoad(() => refreshFiles(datasetId), [datasetId], () => toast('文件列表加载失败', { tone: 'error' }));

  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [batchIds, setBatchIds] = useState<string[]>([]);

  const upload = (list: File[]) => {
    if (!dataset) return;
    const tooLarge = list.filter((f) => f.size > MAX_SIZE);
    const ok = list.filter((f) => f.size <= MAX_SIZE);
    if (tooLarge.length) toast(`${tooLarge.length} 个文件超过 50 MB，已跳过`, { tone: 'error' });
    if (!ok.length) return;
    const ids = uploadFiles(dataset.id, ok, dataset.autoParse);
    setBatchIds((prev) => [...prev.filter((id) => files.some((f) => f.id === id && f.status === 'uploading')), ...ids]);
  };
  const pickers = useFilePickers({ onFiles: upload });

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return files.filter((f) => matchFilter[filter](f) && (!q || f.name.toLowerCase().includes(q)));
  }, [files, filter, query]);

  if (!loaded) return <PageLoading />;
  if (!dataset) {
    return (
      <PageColumn>
        <p className="py-24 text-center text-[13px] text-muted">
          知识库不存在或已被删除。
          <Link to="/datasets" className="ml-1 text-ink underline">
            返回知识库列表
          </Link>
        </p>
      </PageColumn>
    );
  }

  const disabled = dataset.status === 'disabled';
  const isEmpty = stats.total === 0;
  const batch = files.filter((f) => batchIds.includes(f.id));
  const uploading = batch.some((f) => f.status === 'uploading');

  return (
    <PageColumn>
      {pickers.inputs}
      <PageHeader
        eyebrow={<Breadcrumb items={[{ label: '知识库', to: '/datasets' }, { label: dataset.name }]} />}
        title={dataset.name}
        description={`${dataset.description || '暂无描述'} · ${dataset.updatedAt === '刚刚' && isEmpty ? '刚刚创建' : `更新于${dataset.updatedAt}`}`}
        actions={
          <div className="flex gap-3.5 text-[11.5px] text-text2">
            <Link to={`/datasets/${dataset.id}/config`} className="hover:text-ink">
              解析配置
            </Link>
            <button type="button" onClick={() => actions.open('edit', dataset)} className="hover:text-ink">
              编辑
            </button>
          </div>
        }
      />

      {disabled && (
        <div role="status" className="mb-6 flex items-center gap-2.5 rounded-xl bg-soft px-4 py-3 text-[12px] text-text2">
          <Power aria-hidden className="size-3.5 text-muted" />
          该知识库已停用：对话中不可选择，也不能上传或解析新文件。
          <span className="flex-1" />
          <Button icon={<Power className="size-3" />} onClick={() => actions.enable(dataset)}>
            重新启用
          </Button>
        </div>
      )}

      {uploading && batch.length > 0 && (
        <UploadTray
          batch={batch}
          onCancel={() => {
            cancelUploads(dataset.id);
            setBatchIds([]);
            toast('已取消未完成的上传');
          }}
        />
      )}

      {!isEmpty && !uploading && (
        <ParseSummaryCard
          dataset={dataset}
          stats={stats}
          disabled={disabled}
          onUpload={pickers.pickFiles}
          onParseAll={() => {
            parseAll(dataset.id);
            toast('已开始解析待处理与失败的文件');
          }}
          onClearFailed={() => clearFailed(dataset.id)}
        />
      )}

      <div className={isEmpty || uploading ? '' : 'mt-7'}>
        <div className="flex items-center gap-2.5">
          <h2 className="flex items-baseline gap-2 text-[15px] font-medium text-ink">
            文件<span className="font-num text-[12px] text-muted">{stats.total}</span>
          </h2>
          <Segmented
            ariaLabel="按状态筛选"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: '全部', count: stats.total },
              { value: 'done', label: '已完成', count: stats.done },
              { value: 'running', label: stats.uploading ? '进行中' : '解析中', count: stats.running },
              { value: 'failed', label: '失败', count: stats.failed, countTone: 'red' },
            ]}
          />
          <span className="flex-1" />
          {stats.failed > 0 && uploading && (
            <button type="button" onClick={() => clearFailed(dataset.id)} className="text-[11.5px] text-text2 hover:text-ink">
              清除全部失败文件
            </button>
          )}
          {!isEmpty && <SearchBox value={query} onChange={setQuery} placeholder="搜索文件..." className="w-[200px]" />}
        </div>

        {isEmpty ? (
          <>
            <div className="mt-3.5">
              <Dropzone
                onFiles={upload}
                disabled={disabled}
                autoParse={dataset.autoParse}
                onAutoParseChange={(v) => void updateDataset(dataset.id, { autoParse: v })}
              />
            </div>
            <NextSteps datasetId={dataset.id} />
          </>
        ) : (
          <>
            <div className="mt-3.5 flex items-center gap-3 border-b border-divider pb-2.5 text-[11px] text-muted">
              <span className="w-[30px]" />
              <span className="flex-1">文件名</span>
              <span className="w-[110px]">类型 · 大小</span>
              <span className="w-[110px]">状态</span>
              <span className="w-14 text-right">更新</span>
              <span className="w-[18px]" />
            </div>
            {visible.length ? (
              <ul>
                {visible.map((f) => (
                  <FileRow key={f.id} file={f} disabled={disabled} />
                ))}
              </ul>
            ) : (
              <p className="py-12 text-center text-[12.5px] text-muted">没有符合条件的文件</p>
            )}
            {filter === 'all' && !query && stats.total > files.length && (
              <p className="pt-4 text-center text-[11.5px] text-muted">
                已显示最近 {files.length} 个文件，其余 {stats.total - files.length} 个已完成解析的文件可通过搜索查找
              </p>
            )}
          </>
        )}
      </div>
      {actions.dialogs}
    </PageColumn>
  );
}
