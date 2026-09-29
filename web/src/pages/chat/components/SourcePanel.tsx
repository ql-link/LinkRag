import { ArrowLeft, ChevronLeft, ChevronRight, Copy, ExternalLink, FileText } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { FileBadge } from '@/components/FileBadge';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import type { AssistantMessage, RetrievedChunk } from '@/services/chat';
import { fileCount } from '@/services/datasets';
import { useStore } from '@/services/useStore';

interface Props {
  answer?: AssistantMessage;
  datasetIds: string[];
  /** 当前查看原文的片段编号；为空时显示片段列表 */
  active?: number;
  onSelect: (n?: number) => void;
}

const Section = ({ label, count, children }: { label: string; count?: string; children?: React.ReactNode }) => (
  <div className="flex h-[14px] items-center text-[11px] text-muted">
    <h3 className="font-normal">{label}</h3>
    <span className="flex-1" />
    {count}
    {children}
  </div>
);

/** 回答中被引用的片段编号 → 回答中的第几项（F6「引用于回答第 N 项」） */
function citedIn(answer: AssistantMessage | undefined, n: number) {
  const b = answer?.blocks.find((x) => x.cite?.includes(n));
  return b?.kind === 'item' ? `回答第 ${b.n} 项` : b ? '回答正文' : undefined;
}

/** F2 右侧面板：召回片段 + 知识库文件；F6 点击片段后切换为原文预览 */
export function SourcePanel({ answer, datasetIds, active, onSelect }: Props) {
  const chunks = answer?.chunks ?? [];
  const current = chunks.find((c) => c.n === active);
  return (
    <aside aria-label="引用来源" className="flex h-full w-[320px] shrink-0 flex-col overflow-y-auto border-l border-divider bg-[#fafaf8] px-6 pt-[22px] pb-6">
      {current ? (
        <Preview chunk={current} chunks={chunks} answer={answer} onSelect={onSelect} />
      ) : (
        <>
          <Section label="召回片段" count={answer ? `${chunks.length} 个` : undefined} />
          <div className="h-[18px]" />
          {!answer || (answer.status === 'thinking' && !chunks.length) ? (
            <div aria-busy className="flex flex-col gap-2.5">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-[107px] animate-pulse rounded-xl bg-white/80" />
              ))}
            </div>
          ) : !chunks.length ? (
            <p className="rounded-xl border border-dashed border-dash px-4 py-6 text-center text-[12px] text-muted">没有召回到相关片段</p>
          ) : (
            <ul className="flex flex-col gap-2.5">
              {chunks.map((c, i) => (
                <li key={c.n} style={{ animationDelay: `${i * 40}ms` }} className="animate-rise-in">
                  <ChunkCard chunk={c} cited={!!answer.blocks.some((b) => b.cite?.includes(c.n))} onClick={() => onSelect(c.n)} />
                </li>
              ))}
            </ul>
          )}
          <div className="h-6" />
          <Files datasetIds={datasetIds} />
        </>
      )}
    </aside>
  );
}

function ChunkCard({ chunk: c, cited, onClick }: { chunk: RetrievedChunk; cited: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex w-full flex-col gap-2 rounded-xl border bg-white px-3.5 py-3 text-left shadow-[0_3px_10px_0_rgba(0,0,0,0.04)] transition-colors',
        cited ? 'border-ink/70 hover:border-ink' : 'border-line hover:border-[#cfcfc9]',
      )}
    >
      <span className="flex w-full items-center gap-1.5">
        <span className="text-[11.5px] font-medium text-ink">片段 {c.n}</span>
        {c.location && <span className="text-[11px] text-muted">· {c.location}</span>}
        <span className="flex-1" />
        {Number.isFinite(c.score) && <span className={cn('font-num text-[11px] font-medium', c.score >= 0.8 ? 'text-green' : 'text-muted')}>{c.score.toFixed(2)}</span>}
      </span>
      <span className="line-clamp-2 text-[12px] leading-[19px] text-text2">{c.text}</span>
      <span className="flex items-center gap-[5px] text-[10.5px] text-muted">
        <FileText aria-hidden className="size-[11px]" />
        <span className="truncate">{c.fileName}</span>
      </span>
    </button>
  );
}

function Files({ datasetIds }: { datasetIds: string[] }) {
  const navigate = useNavigate();
  const files = useStore((s) => s.files.filter((f) => datasetIds.includes(f.datasetId) && f.status === 'done').slice(0, 5));
  const total = datasetIds.reduce((n, id) => n + fileCount(id), 0);
  if (!datasetIds.length) return null;
  return (
    <>
      <Section label="文件" count={String(total)} />
      <div className="h-2.5" />
      <ul className="flex flex-col">
        {files.map((f) => (
          <li key={f.id}>
            <button type="button" onClick={() => navigate(`/datasets/${f.datasetId}/files/${f.id}`)} className="-mx-2 flex w-[calc(100%+16px)] items-center gap-2.5 rounded-lg px-2 py-[7px] text-left hover:bg-white">
              <FileBadge type={f.type} className="size-6 rounded-[6px] text-[7.5px]" />
              <span className="truncate text-[12px] text-text2">{f.name}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

/** F6 原文预览：顶部返回 + 引用间切换，文件信息卡、命中段落（左侧色条标记）与上下文，底部打开文件详情 */
function Preview({ chunk: c, chunks, answer, onSelect }: { chunk: RetrievedChunk; chunks: RetrievedChunk[]; answer?: AssistantMessage; onSelect: (n?: number) => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  // 在回答中被引用的片段之间切换；若当前片段未被引用，则在全部召回片段中切换
  const cited = chunks.filter((x) => answer?.blocks.some((b) => b.cite?.includes(x.n)));
  const list = cited.some((x) => x.n === c.n) ? cited : chunks;
  const i = list.findIndex((x) => x.n === c.n);
  const where = citedIn(answer, c.n);
  const hit = c.full ?? c.text.replace(/…$/, '');
  const high = Number.isFinite(c.score) && c.score >= 0.8;
  const openFile = () => navigate(`/datasets/${c.datasetId}/files/${c.fileId}`);

  return (
    <div key={c.n} className="flex min-h-full animate-rise-in flex-col">
      <div className="flex h-[14px] items-center text-[11px] text-muted">
        <button type="button" onClick={() => onSelect(undefined)} className="-ml-1 flex items-center gap-1 rounded px-1 hover:text-ink">
          <ArrowLeft aria-hidden className="size-3" />
          召回片段
        </button>
        <span className="flex-1" />
        <span className="flex items-center gap-0.5">
          <NavButton label="上一个片段" disabled={i <= 0} onClick={() => onSelect(list[i - 1].n)}>
            <ChevronLeft />
          </NavButton>
          <span className="min-w-[34px] text-center font-num font-medium text-text2">
            {i + 1} / {list.length}
          </span>
          <NavButton label="下一个片段" disabled={i >= list.length - 1} onClick={() => onSelect(list[i + 1].n)}>
            <ChevronRight />
          </NavButton>
        </span>
      </div>
      <div className="h-[18px]" />
      <h3 className="flex items-baseline gap-2">
        <span className="font-serif text-[17px] font-semibold text-ink">片段 {c.n}</span>
        <span className="text-[11.5px] text-muted">{where ? `引用于${where}` : '未被回答引用'}</span>
      </h3>
      <div className="h-3" />
      <div className="flex flex-wrap gap-1.5 font-num text-[10.5px] font-medium">
        {Number.isFinite(c.score) && <span className={cn('rounded-[6px] px-2 py-[3px]', high ? 'bg-green/10 text-green' : 'bg-soft text-text2')}>相关度 {c.score.toFixed(2)}</span>}
        {!c.full && <span className="rounded-[6px] bg-soft px-2 py-[3px] text-text2">稠密 + BM25</span>}
        <span className="rounded-[6px] bg-soft px-2 py-[3px] text-text2">{c.tokens} Token</span>
      </div>
      <div className="h-4" />
      <button type="button" onClick={openFile} title="在文件详情中打开" className="group flex items-center gap-2.5 rounded-[10px] border border-line bg-white px-3 py-2.5 text-left transition-colors hover:border-[#cfcfc9]">
        <FileBadge type={c.fileType} className="size-7 text-[8px]" />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate text-[12.5px] font-medium text-ink">{c.fileName}</span>
          <span className="truncate text-[10.5px] text-muted">{[c.datasetName, c.location].filter(Boolean).join(' · ')}</span>
        </span>
        <ExternalLink aria-hidden className="size-3.5 shrink-0 text-muted group-hover:text-ink" />
      </button>
      <div className="h-6" />
      <div className="flex items-center text-[11px] text-muted">
        <span>原文</span>
        <span className="flex-1" />
        <button
          type="button"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText([c.before, hit, c.after].filter(Boolean).join('\n'));
              toast('已复制原文', { tone: 'success' });
            } catch {
              toast('复制失败，请手动选择文本', { tone: 'error' });
            }
          }}
          className="-mr-1 flex items-center gap-1 rounded px-1 hover:text-ink"
        >
          <Copy aria-hidden className="size-3" />
          复制
        </button>
      </div>
      <div className="h-2.5" />
      <div className="flex flex-col gap-3 rounded-xl border border-line bg-white px-4 py-3.5 text-[12.5px] leading-[21px] whitespace-pre-wrap break-words shadow-[0_3px_10px_0_rgba(0,0,0,0.04)]">
        {c.before && <p className="text-muted">{c.before}</p>}
        <p className="border-l-2 border-[#c8925a] pl-3 text-ink">
          <mark className="bg-transparent text-inherit">{hit}</mark>
        </p>
        {c.after && <p className="text-muted">{c.after}</p>}
      </div>
      <div className="min-h-6 flex-1" />
      <button type="button" onClick={openFile} className="flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-[8px] bg-ink text-[12.5px] font-medium text-white transition-opacity hover:opacity-90">
        在文件详情中打开
        <ExternalLink aria-hidden className="size-3.5" />
      </button>
    </div>
  );
}

function NavButton({ label, disabled, onClick, children }: { label: string; disabled: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} disabled={disabled} onClick={onClick} className="flex size-5 items-center justify-center rounded hover:bg-active hover:text-ink disabled:pointer-events-none disabled:opacity-35 [&>svg]:size-3.5">
      {children}
    </button>
  );
}
