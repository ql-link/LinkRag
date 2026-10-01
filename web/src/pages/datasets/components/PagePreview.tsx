import { AlertCircle, ZoomIn, ZoomOut } from 'lucide-react';
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react';

import { Segmented } from '@/components/ui/Segmented';
import { USE_MOCK } from '@/api/http';
import { cn } from '@/lib/cn';
import { useElementWidth } from '@/lib/useElementWidth';
import { samplePageChunks, type Chunk } from '@/mock/chunks';

import { MarkdownBody } from './MarkdownBody';

/** 原文页面按 A4 比例排版：基准宽 595，再整体缩放到预览区宽度 */
const PAGE_W = 595;
const PAGE_H = 842;
const FIT_PADDING = 56;
const MAX_FIT_SCALE = 1.6;

const Bar = ({ w }: { w: string }) => <div style={{ width: w }} className="h-[6px] rounded-[2px] bg-divider" />;

/** 段落之间的占位行，模拟正文密度（按序号确定，避免重渲染抖动） */
function Filler({ seed }: { seed: number }) {
  const widths = ['100%', '96%', '92%', '98%', '88%', '94%'];
  const n = 2 + (seed % 2);
  return (
    <div className="flex flex-col gap-[9px] py-1">
      {Array.from({ length: n }).map((_, i) => (
        <Bar key={i} w={widths[(seed + i) % widths.length]} />
      ))}
    </div>
  );
}

interface CanvasProps {
  chunks: Chunk[];
  page: number;
  selectedId?: string;
  onSelect?: (c: Chunk) => void;
  dim?: boolean;
}

/** 单页原文：按当前页的分块顺序渲染标题、正文、表格与图片，选中分块虚线高亮 */
export function PageCanvas({ chunks, page, selectedId, onSelect, dim }: CanvasProps) {
  const blocks = chunks.length ? chunks : dim ? samplePageChunks : [];
  const refs = useRef(new Map<string, HTMLElement>());

  useEffect(() => {
    if (selectedId) refs.current.get(selectedId)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [selectedId, page]);

  let lastSection = '';
  return (
    <div
      style={{ width: PAGE_W, minHeight: PAGE_H }}
      className={cn('flex flex-col gap-3 rounded-[4px] border border-line bg-white px-12 pt-12 pb-14 shadow-[0_6px_20px_0_rgba(0,0,0,0.06)]', dim && 'opacity-90')}
    >
      {blocks.map((c, i) => {
        const heading = USE_MOCK && c.section !== lastSection ? (lastSection = c.section) : null;
        const selected = c.id === selectedId;
        const box = (children: ReactNode, extra?: string) => (
          <div
            ref={(el) => {
              if (el) refs.current.set(c.id, el);
              else refs.current.delete(c.id);
            }}
            role={onSelect ? 'button' : undefined}
            tabIndex={onSelect ? 0 : undefined}
            aria-label={onSelect ? `选中分块 #${c.index}` : undefined}
            aria-pressed={onSelect ? selected : undefined}
            onClick={onSelect ? () => onSelect(c) : undefined}
            onKeyDown={onSelect ? (e) => e.key === 'Enter' && onSelect(c) : undefined}
            className={cn(
              'min-w-0 rounded-[3px] border border-dashed px-2 py-1.5 transition-colors',
              selected ? 'border-amber bg-amber/10' : 'border-transparent',
              onSelect && !selected && 'cursor-pointer hover:border-dash hover:bg-soft/60',
              extra,
            )}
          >
            {children}
          </div>
        );
        return (
          <Fragment key={c.id}>
            {heading && <h3 className={cn('font-semibold text-ink', i === 0 ? 'text-[20px]' : 'mt-2 text-[15px]')}>{heading}</h3>}
            {c.kind === 'table' && c.table
              ? box(
                  <table className="w-full border-collapse overflow-hidden rounded-[3px] border border-line text-[12px]">
                    <tbody>
                      {c.table.map((row, r) => (
                        <tr key={r} className={r === 0 ? 'bg-soft font-medium text-ink' : 'border-t border-divider text-text2'}>
                          {row.map((cell, k) => (
                            <td key={k} className="px-3 py-2">
                              {cell}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>,
                )
              : c.kind === 'image' && c.imageCaption
                ? box(
                    <figure className="flex flex-col items-center gap-2 rounded bg-soft py-5">
                      <div className="flex items-center gap-2 text-[11.5px]">
                        {['上传', '版面', 'OCR', '入库'].map((s, k) => (
                          <span key={s} className="flex items-center gap-2">
                            {k > 0 && <span className="text-muted">→</span>}
                            <span className="rounded border border-line bg-white px-2 py-1 text-text2">{s}</span>
                          </span>
                        ))}
                      </div>
                      <figcaption className="text-[11px] text-muted">
                        {c.imageCaption} {c.imageTitle ?? '示意图'}
                      </figcaption>
                    </figure>,
                  )
                : box(<MarkdownBody>{c.text}</MarkdownBody>)}
            {c.kind === 'text' && <Filler seed={c.index} />}
          </Fragment>
        );
      })}
      {!blocks.length && <p className="text-[13px] text-muted">当前页暂无正文内容</p>}
      <Filler seed={page + 3} />
    </div>
  );
}

/** 按预览区宽度计算缩放；zoom 为用户额外缩放百分比 */
function ScaledPage({ zoom, children }: { zoom: number; children: ReactNode }) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const fit = width ? Math.min(MAX_FIT_SCALE, (width - FIT_PADDING) / PAGE_W) : 1;
  const scale = Math.max(0.3, fit * (zoom / 100));
  return (
    <div ref={ref} className="min-h-0 min-w-0 flex-1 overflow-auto px-7 pt-2 pb-24">
      <div style={{ zoom: scale }} className="mx-auto w-fit">
        {children}
      </div>
    </div>
  );
}

function Thumbnails({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  const count = Math.min(7, pages);
  const start = Math.min(pages - count + 1, Math.max(1, page - 3));
  return (
    <div className="flex w-[68px] shrink-0 flex-col items-center gap-2.5 overflow-y-auto px-3 pt-2">
      {Array.from({ length: count }, (_, i) => start + i).map((p) => (
        <button key={p} type="button" onClick={() => onPage(p)} aria-label={`第 ${p} 页`} aria-current={p === page} className="flex flex-col items-center gap-1">
          <span className={cn('flex aspect-[595/842] w-11 flex-col gap-1 rounded-[3px] bg-white px-1.5 pt-2', p === page ? 'border-[1.5px] border-ink' : 'border border-line hover:border-dash')}>
            <span className="h-[3px] w-6 rounded-[1px] bg-dash" />
            <span className="h-0.5 w-full rounded-[1px] bg-divider" />
            <span className="h-0.5 w-11/12 rounded-[1px] bg-divider" />
            <span className="h-0.5 w-full rounded-[1px] bg-divider" />
            <span className="h-0.5 w-10/12 rounded-[1px] bg-divider" />
          </span>
          <span className={cn('text-[9.5px] font-medium', p === page ? 'text-ink' : 'text-muted')}>{p}</span>
        </button>
      ))}
    </div>
  );
}

interface PreviewPaneProps {
  page: number;
  pages: number;
  onPage: (p: number) => void;
  pageChunks: Chunk[];
  selectedId?: string;
  onSelect: (c: Chunk) => void;
  markdown: string;
}

/** C6 左侧：原文 / 解析结果 Markdown 切换、缩略图、自适应缩放与翻页 */
export function PreviewPane({ page, pages, onPage, pageChunks, selectedId, onSelect, markdown }: PreviewPaneProps) {
  const [tab, setTab] = useState<'raw' | 'md'>('raw');
  const [zoom, setZoom] = useState(100);

  return (
    <div className="relative flex h-full min-h-0 flex-col bg-soft">
      <div className="flex h-12 shrink-0 items-center gap-2.5 pr-3.5 pl-4">
        <Segmented
          ariaLabel="预览模式"
          value={tab}
          onChange={setTab}
          options={[
            { value: 'raw', label: '原文' },
            { value: 'md', label: '解析结果 Markdown' },
          ]}
        />
        <span className="flex-1" />
        {tab === 'raw' && (
          <>
            <button type="button" aria-label="缩小" disabled={zoom <= 50} onClick={() => setZoom((z) => z - 10)} className="text-text2 hover:text-ink disabled:opacity-40">
              <ZoomOut className="size-3.5" />
            </button>
            <button type="button" aria-label="重置缩放" onClick={() => setZoom(100)} className="w-10 text-center font-num text-[11px] font-medium text-ink">
              {zoom}%
            </button>
            <button type="button" aria-label="放大" disabled={zoom >= 200} onClick={() => setZoom((z) => z + 10)} className="text-text2 hover:text-ink disabled:opacity-40">
              <ZoomIn className="size-3.5" />
            </button>
          </>
        )}
      </div>
      {tab === 'raw' ? (
        <div className="flex min-h-0 flex-1">
          <Thumbnails page={page} pages={pages} onPage={onPage} />
          <ScaledPage zoom={zoom}>
            <PageCanvas chunks={pageChunks} page={page} selectedId={selectedId} onSelect={onSelect} />
          </ScaledPage>
        </div>
      ) : (
        <div className="m-4 mt-0 min-h-0 min-w-0 flex-1 overflow-auto rounded-md border border-line bg-white p-6">
          {markdown.trim() ? <MarkdownBody>{markdown}</MarkdownBody> : <p className="text-[13px] text-muted">暂无正文内容</p>}
        </div>
      )}
      {tab === 'raw' && (
        <div className="absolute bottom-6 left-1/2 flex -translate-x-1/2 items-center gap-2.5 rounded-lg border border-line bg-white px-2.5 py-[5px] shadow-[0_4px_12px_0_rgba(0,0,0,0.06)]">
          <button type="button" aria-label="上一页" disabled={page <= 1} onClick={() => onPage(page - 1)} className="text-[13px] text-muted hover:text-ink disabled:opacity-40">
            ‹
          </button>
          <span className="font-num text-[11px] font-medium text-ink">
            第 {page} / {pages} 页
          </span>
          <button type="button" aria-label="下一页" disabled={page >= pages} onClick={() => onPage(page + 1)} className="text-[13px] text-muted hover:text-ink disabled:opacity-40">
            ›
          </button>
        </div>
      )}
    </div>
  );
}

/** C7 左侧：失败文件的原文预览 + 失败页标记 */
export function FailedPreview({ failedPage }: { failedPage: number }) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-soft">
      <div className="flex h-12 shrink-0 items-center gap-2.5 pr-3.5 pl-4">
        <Segmented ariaLabel="预览模式" value="raw" onChange={() => {}} options={[{ value: 'raw', label: '原文' }, { value: 'md', label: '解析结果 Markdown' }]} />
        <span className="flex-1" />
        <span className="text-[11px] text-muted">解析失败，暂无解析结果</span>
      </div>
      <ScaledPage zoom={100}>
        <div className="relative">
          <PageCanvas chunks={[]} page={failedPage} dim />
          <span className="absolute top-5 left-5 flex items-center gap-[5px] rounded-md bg-red px-2.5 py-1 text-[12px] font-medium text-white">
            <AlertCircle aria-hidden className="size-3" />第 {failedPage} 页 · 识别超时
          </span>
        </div>
      </ScaledPage>
    </div>
  );
}
