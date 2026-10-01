import { ArrowLeft, ChevronDown, Download, Loader2, MessageSquare, MoreHorizontal, RefreshCw, SlidersHorizontal, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { FileBadge } from '@/components/FileBadge';
import { PageLoading } from '@/components/ui/Loading';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { Menu } from '@/components/ui/Menu';
import { Progress } from '@/components/ui/Progress';
import { useToast } from '@/contexts/ToastContext';
import { USE_MOCK } from '@/api/http';
import { pageCount, type Chunk } from '@/mock/chunks';
import { db } from '@/mock/db';
import { usePageLoad } from '@/lib/usePageLoad';
import { fetchChunks, refreshFiles, removeFile, reparseFile } from '@/services/datasets';
import { useStore } from '@/services/useStore';

import { ChunkList } from './components/ChunkList';
import { FailurePanel } from './components/FailurePanel';
import { FailedPreview, PreviewPane } from './components/PagePreview';

function toMarkdown(chunks: Chunk[]): string {
  let last = '';
  return chunks
    .map((c) => {
      const head = c.section !== last ? `## ${(last = c.section)}\n\n` : '';
      if (c.table) return head + c.table.map((r, i) => `| ${r.join(' | ')} |${i === 0 ? `\n|${r.map(() => ' --- ').join('|')}|` : ''}`).join('\n');
      if (c.kind === 'image') return `${head}![${c.imageCaption}](image)\n\n> ${c.text}`;
      return head + c.text;
    })
    .join('\n\n');
}

/** C6 文件详情 · 分块预览 / C7 解析失败 */
export default function FileDetailPage() {
  const { datasetId = '', fileId = '' } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const dataset = useStore((s) => s.datasets.find((d) => d.id === datasetId));
  const file = useStore((s) => s.files.find((f) => f.id === fileId));

  // 文件列表（直达时可能尚未拉取）与分块全部返回后再一次性展示页面
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const loaded = usePageLoad(
    async () => {
      setChunks([]);
      if (!USE_MOCK && datasetId) await refreshFiles(datasetId).catch(() => undefined);
      const f = db.state.files.find((x) => x.id === fileId);
      if (f?.status === 'done') setChunks(await fetchChunks(f));
    },
    [datasetId, fileId],
    () => toast('分块加载失败', { tone: 'error' }),
  );
  // 页面已展示后文件才解析完成（重新解析）：静默补拉分块，不再回到整页加载
  const parsed = file?.status === 'done';
  useEffect(() => {
    if (!loaded || !parsed || !file) return;
    let alive = true;
    fetchChunks(file)
      .then((list) => alive && setChunks(list))
      .catch(() => alive && toast('分块加载失败', { tone: 'error' }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parsed]);
  // 真实后端未提供页码：统一按 1 页展示
  const pages = !file || !USE_MOCK ? 1 : file.name.includes('产品需求文档') ? 32 : file.status === 'failed' ? 46 : pageCount(file);
  const initial = chunks.find((c) => c.index === 31) ?? chunks[0];
  const [selectedId, setSelectedId] = useState<string | undefined>(initial?.id);
  const [page, setPage] = useState(initial?.page ?? 1);

  useEffect(() => {
    setSelectedId(initial?.id);
    setPage(initial?.page ?? 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileId, chunks.length]);

  if (!dataset || !file) {
    if (!loaded) return <PageLoading />;
    return (
      <p className="py-24 text-center text-[13px] text-muted">
        文件不存在或已被删除。
        <Link to={`/datasets/${datasetId}`} className="ml-1 text-ink underline">
          返回知识库
        </Link>
      </p>
    );
  }

  if (!loaded) return <PageLoading />;

  const disabled = dataset.status === 'disabled';
  const failed = file.status === 'failed';
  const done = file.status === 'done';
  /** 翻页时若当前选中的分块不在新页，自动选中新页第一个分块，保持左右联动 */
  const goPage = (p: number) => {
    setPage(p);
    const cur = chunks.find((c) => c.id === selectedId);
    if (cur?.page !== p) setSelectedId(chunks.find((c) => c.page === p)?.id);
  };
  const tokensAvg = chunks.length ? Math.round(chunks.reduce((n, c) => n + c.tokens, 0) / chunks.length) : 0;
  const images = chunks.filter((c) => c.kind === 'image').length;
  const tables = chunks.filter((c) => c.kind === 'table').length;

  const del = () => {
    removeFile(file.id);
    toast(`已删除「${file.name}」`, { tone: 'success' });
    navigate(`/datasets/${dataset.id}`);
  };

  return (
    <div className="flex h-full min-h-[640px] flex-col">
      <header className="flex h-16 shrink-0 items-center gap-3 border-b border-divider pr-5 pl-6">
        <Link to={`/datasets/${dataset.id}`} aria-label="返回知识库" className="rounded-[7px] border border-line px-2 py-[7px] text-text2 hover:bg-soft">
          <ArrowLeft className="size-3" />
        </Link>
        <FileBadge type={file.type} className="size-8" />
        <div className="flex min-w-0 flex-col gap-[3px]">
          <div className="flex items-center gap-1.5">
            <Link to={`/datasets/${dataset.id}`} className="text-[11px] text-muted hover:text-ink">
              {dataset.name}
            </Link>
            <span className="text-[11px] text-faint">/</span>
            <h1 className="truncate text-[13.5px] font-medium text-ink">{file.name}</h1>
          </div>
          <p className="text-[11px] text-muted">
            {file.type} · {file.size} · {pages} 页 · 上传于 {file.uploadedAt ?? '09-24'}{done ? ` · 解析于${file.updatedAt}` : ''}
          </p>
        </div>
        {done && <Chip tone="green">已完成</Chip>}
        {failed && <Chip tone="red">失败</Chip>}
        {(file.status === 'parsing' || file.status === 'queued') && <Chip tone={file.status === 'parsing' ? 'amber' : 'gray'}>{file.status === 'parsing' ? `解析中 ${file.progressEstimated ? '≈' : ''}${file.progress}%` : '待解析'}</Chip>}
        <span className="flex-1" />
        <Button variant="secondary" icon={<Download className="size-3" />} onClick={() => toast('Mock 模式下不提供下载')}>
          下载
        </Button>
        {failed ? (
          <Button variant="secondary" className="text-red" icon={<Trash2 className="size-3" />} onClick={del}>
            删除
          </Button>
        ) : (
          <>
            <Button variant="secondary" icon={<RefreshCw className="size-3" />} disabled={disabled || file.status === 'parsing'} onClick={() => reparseFile(file.id)}>
              重新解析
            </Button>
            <Button variant="secondary" icon={<MessageSquare className="size-3" />} onClick={() => navigate('/chat', { state: { datasetIds: [dataset.id], question: `基于《${file.name}》，` } })}>
              基于此文件提问
            </Button>
            <Menu
              width={140}
              items={[{ key: 'del', label: '删除文件', icon: <Trash2 />, danger: true, onSelect: del }]}
              trigger={({ toggle }) => (
                <button type="button" aria-label="更多操作" onClick={toggle} className="rounded-[7px] border border-line px-2 py-[7px] text-text2 hover:bg-soft">
                  <MoreHorizontal className="size-3" />
                </button>
              )}
            />
          </>
        )}
      </header>

      {done && (
        <div className="flex h-[62px] shrink-0 items-center border-b border-divider bg-[#fafaf8] px-6">
          {(USE_MOCK
            ? [
                ['解析方案', 'MinerU'],
                ['分块', `${chunks.length} 个`],
                ['平均长度', `${tokensAvg} Token`],
                ['图片', `${images} 张 · 已增强`],
                ['表格', `${tables} 个 · 已增强`],
                ['耗时', '1 分 42 秒'],
              ]
            : // 真实模式只展示可由分块计算的指标；解析方案 / 耗时后端未提供
              [
                ['分块', `${chunks.length} 个`],
                ['平均长度', `${tokensAvg} Token`],
                ['图片', `${images} 张`],
                ['表格', `${tables} 个`],
              ]
          ).map(([k, v], i) => (
            <div key={k} className="flex items-center">
              {i > 0 && <span className="h-[26px] w-px bg-divider" />}
              <div className={i === 0 ? 'flex flex-col gap-1 pr-[18px]' : 'flex flex-col gap-1 px-[18px]'}>
                <span className="text-[10.5px] text-muted">{k}</span>
                <span className="text-[12.5px] font-medium text-ink">{v}</span>
              </div>
            </div>
          ))}
          <span className="flex-1" />
          <Link to={`/datasets/${dataset.id}/config`} className="flex items-center gap-[5px] text-[11.5px] text-text2 hover:text-ink">
            <SlidersHorizontal aria-hidden className="size-3" />
            解析配置：{dataset.name}默认
            <ChevronDown aria-hidden className="size-2.5" />
          </Link>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="min-w-[480px] flex-[11] border-r border-divider">
          {failed ? (
            <FailedPreview failedPage={18} />
          ) : (
            <PreviewPane
              page={page}
              pages={pages}
              onPage={goPage}
              pageChunks={chunks.filter((c) => c.page === page)}
              selectedId={selectedId}
              onSelect={(c) => setSelectedId(c.id)}
              markdown={toMarkdown(chunks)}
            />
          )}
        </div>
        <div className="min-w-[440px] flex-[9]">
          {failed ? (
            <FailurePanel
              file={file}
              pages={pages}
              failedPage={18}
              disabled={disabled}
              onResume={() => {
                reparseFile(file.id);
                toast('已从第 18 页继续解析');
              }}
              onRestart={() => {
                reparseFile(file.id);
                toast('已重新开始完整解析');
              }}
            />
          ) : done ? (
            <ChunkList
              chunks={chunks}
              page={page}
              pages={pages}
              onPage={goPage}
              selectedId={selectedId}
              onSelect={(c) => {
                setSelectedId(c.id);
                setPage(c.page);
              }}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-[12.5px] text-muted">
              <Loader2 aria-hidden className="size-5 animate-spin text-amber" />
              {file.status === 'parsing' ? `正在解析 · ${file.progressEstimated ? '≈' : ''}${file.progress}%` : '文件排队中，解析完成后可预览分块'}
              {file.status === 'parsing' && <Progress value={file.progress} color="#d9912b" className="w-56" label="解析进度" />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
