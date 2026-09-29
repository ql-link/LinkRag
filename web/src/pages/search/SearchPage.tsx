import { ArrowRight, Check, ChevronDown, Clock, Database, FileText, Info, MessageSquare, Plus, RefreshCw, Search, Sparkles, Upload, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { Breadcrumb } from '@/components/Breadcrumb';
import { FileBadge } from '@/components/FileBadge';
import { Highlight } from '@/components/search/Highlight';
import { SectionLabel } from '@/components/SectionLabel';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { Kbd } from '@/components/ui/Kbd';
import { useToast } from '@/contexts/ToastContext';
import { PageColumn } from '@/layouts/AppLayout';
import { cn } from '@/lib/cn';
import {
  clearRecentSearches,
  hitLabel,
  pushRecentSearch,
  QUERY_MAX,
  recentSearches,
  search,
  suggestions,
  type SearchFilters,
  type SearchScope,
  type SearchSort,
  type SearchTime,
} from '@/services/search';
import { useStore } from '@/services/useStore';
import type { FileType } from '@/types';

const scopeLabel: Record<SearchScope, string> = { all: '全部', file: '文件', conversation: '对话', dataset: '知识库' };
const timeLabel: Record<SearchTime, string> = { any: '不限', '7d': '近 7 天', '30d': '近 30 天' };
const sortLabel: Record<SearchSort, string> = { relevance: '相关度', recent: '最近更新' };
const TYPES: FileType[] = ['PDF', 'DOCX', 'MD', 'TXT', 'XLSX'];

/** B3 搜索结果 / B5 无结果：地址栏 ?q= 驱动，筛选项也同步到地址栏便于分享 */
export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const datasets = useStore((s) => s.datasets);
  useStore((s) => s.files);

  const q = params.get('q') ?? '';
  const scope = (params.get('scope') as SearchScope) || 'all';
  const filters: SearchFilters = {
    datasetId: params.get('ds') || undefined,
    type: (params.get('type') as FileType) || undefined,
    time: (params.get('time') as SearchTime) || 'any',
    sort: (params.get('sort') as SearchSort) || 'relevance',
  };
  const [draft, setDraft] = useState(q);
  const [recent, setRecent] = useState(recentSearches);
  const [regenKey, setRegenKey] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setDraft(q), [q]);
  useEffect(() => {
    if (q) {
      pushRecentSearch(q);
      setRecent(recentSearches());
    }
  }, [q]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const result = useMemo(() => search(q, filters), [q, filters.datasetId, filters.type, filters.time, filters.sort, datasets]);
  const total = result.files.length + result.conversations.length + result.datasets.length;
  const empty = !!q && total === 0;

  const set = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setParams(next, { replace: true });
  };
  const submit = (value = draft) => {
    const v = value.trim();
    if (v) set({ q: v });
  };
  const clearFilters = () => set({ ds: undefined, type: undefined, time: undefined, sort: undefined });
  /** 向知识库提问：带着问题进入 F1；已按知识库筛选时直接发送 */
  const ask = (question = q || draft) => {
    const datasetIds = filters.datasetId ? [filters.datasetId] : undefined;
    navigate('/chat', { state: { question: question.trim(), datasetIds, autoSend: !!datasetIds } });
  };
  const dsName = datasets.find((d) => d.id === filters.datasetId)?.name;

  const show = (s: SearchScope) => scope === 'all' || scope === s;
  const limit = scope === 'all' ? 4 : Infinity;

  return (
    <PageColumn top={39}>
      <div className="text-[11px]">
        <Breadcrumb items={[{ label: '工作台', to: '/' }, { label: '搜索' }]} />
      </div>

      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="mt-3 flex h-[50px] items-center gap-2.5 rounded-xl border border-ink bg-white pr-2.5 pl-4 shadow-[0_0_0_4px_rgba(28,28,26,0.07)]"
      >
        <Search aria-hidden className="size-4 shrink-0 text-ink" />
        <input
          ref={inputRef}
          autoFocus={!q}
          value={draft}
          maxLength={QUERY_MAX}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setDraft('');
              if (q) set({ q: undefined });
            }
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && draft.trim()) {
              e.preventDefault();
              ask(draft);
            }
          }}
          aria-label="搜索文件、对话与知识库"
          placeholder="搜索文件、对话与知识库…"
          className="min-w-0 flex-1 bg-transparent text-[15px] text-ink placeholder:text-muted"
        />
        <span className="font-num text-[10.5px] font-medium text-faint">
          {draft.length} / {QUERY_MAX}
        </span>
        {draft && (
          <button
            type="button"
            aria-label="清空关键词"
            onClick={() => {
              setDraft('');
              inputRef.current?.focus();
            }}
            className="flex size-[22px] items-center justify-center rounded-[6px] bg-soft text-muted hover:text-ink"
          >
            <X className="size-2.5" />
          </button>
        )}
        <span className="h-5 w-px bg-divider" />
        <Kbd>ESC</Kbd>
      </form>

      {q && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <div role="tablist" aria-label="结果范围" className="flex gap-0.5 rounded-lg bg-soft p-[3px]">
            {(Object.keys(scopeLabel) as SearchScope[]).map((s) => {
              const n = s === 'all' ? total : s === 'file' ? result.files.length : s === 'conversation' ? result.conversations.length : result.datasets.length;
              return (
                <button
                  key={s}
                  role="tab"
                  type="button"
                  aria-selected={scope === s}
                  onClick={() => set({ scope: s === 'all' ? undefined : s })}
                  className={cn(
                    'flex items-center gap-1.5 rounded-md px-[11px] py-[5px] text-[12px] leading-none',
                    scope === s ? 'bg-white font-medium text-ink shadow-seg' : 'text-text2 hover:text-ink',
                  )}
                >
                  {scopeLabel[s]}
                  <span className="font-num text-[10.5px] font-medium text-muted">{n}</span>
                </button>
              );
            })}
          </div>
          <span className="flex-1" />
          <FilterSelect
            label="知识库"
            value={filters.datasetId ?? ''}
            display={dsName ?? '全部'}
            options={[{ value: '', label: '全部' }, ...datasets.map((d) => ({ value: d.id, label: d.name }))]}
            onChange={(v) => set({ ds: v || undefined })}
            onClear={filters.datasetId ? () => set({ ds: undefined }) : undefined}
          />
          <FilterSelect
            label="类型"
            value={filters.type ?? ''}
            display={filters.type ?? '全部'}
            options={[{ value: '', label: '全部' }, ...TYPES.map((t) => ({ value: t, label: t }))]}
            onChange={(v) => set({ type: v || undefined })}
            onClear={filters.type ? () => set({ type: undefined }) : undefined}
          />
          <FilterSelect
            label="时间"
            value={filters.time}
            display={timeLabel[filters.time]}
            options={(Object.keys(timeLabel) as SearchTime[]).map((t) => ({ value: t, label: timeLabel[t] }))}
            onChange={(v) => set({ time: v === 'any' ? undefined : v })}
            onClear={filters.time !== 'any' ? () => set({ time: undefined }) : undefined}
          />
          <FilterSelect
            label="排序"
            value={filters.sort}
            display={sortLabel[filters.sort]}
            options={(Object.keys(sortLabel) as SearchSort[]).map((t) => ({ value: t, label: sortLabel[t] }))}
            onChange={(v) => set({ sort: v === 'relevance' ? undefined : v })}
          />
        </div>
      )}

      <div className="mt-[18px] mb-[22px] h-px bg-divider" />

      <div className="flex items-start gap-8">
        <div className="flex min-w-0 flex-1 flex-col">
          {!q ? (
            <EmptyPrompt />
          ) : empty ? (
            <NoResults
              query={q}
              scopeText={`${dsName ?? '全部知识库'} · ${filters.type ? `${filters.type} 类型` : '全部类型'} · ${filters.time === 'any' ? '不限时间' : timeLabel[filters.time]}`}
              hasFilters={!!(filters.datasetId || filters.type || filters.time !== 'any')}
              onClearFilters={clearFilters}
              onAsk={() => ask()}
              onUpload={() => navigate(filters.datasetId ? `/datasets/${filters.datasetId}` : '/datasets')}
            />
          ) : (
            <>
              {result.summary && scope === 'all' && (
                <section aria-label="AI 摘要" className="mb-[18px] flex flex-col gap-3 rounded-2xl border border-line bg-white px-[18px] py-4 shadow-card">
                  <div className="flex items-center gap-2">
                    <span className="flex size-[22px] items-center justify-center rounded-[6px] bg-ink text-white">
                      <Sparkles aria-hidden className="size-2.5" />
                    </span>
                    <h2 className="text-[12.5px] font-medium text-ink">AI 摘要</h2>
                    <span className="text-[11px] text-muted">
                      检索 {result.summary.datasetCount} 个知识库 · 命中 {result.summary.chunkCount} 个片段 · {result.summary.model}
                    </span>
                  </div>
                  <p key={regenKey} className="animate-[fade-in_300ms_ease-out] text-[13px] leading-[22px] text-ink">
                    <Highlight text={result.summary.text} query={q} strong />
                  </p>
                  <div className="flex items-center gap-1.5">
                    {result.summary.citations.map((c) => (
                      <span key={c.index} className="rounded-[5px] bg-blue/10 px-[7px] py-[3px] text-[10.5px] leading-none font-medium text-blue">
                        片段 {c.index} · {c.title}
                      </span>
                    ))}
                    <span className="flex-1" />
                    <Button
                      variant="secondary"
                      icon={<RefreshCw className="size-3" />}
                      onClick={() => {
                        setRegenKey((k) => k + 1);
                        toast('已重新生成摘要');
                      }}
                    >
                      重新生成
                    </Button>
                    <Button trailingIcon={<ArrowRight className="size-3" />} className="pr-3 pl-[15px]" onClick={() => ask()}>
                      在对话中继续
                    </Button>
                  </div>
                </section>
              )}

              {show('file') && result.files.length > 0 && (
                <ResultGroup label="文件" count={result.files.length} more={scope === 'all' && result.files.length > limit ? () => set({ scope: 'file' }) : undefined}>
                  {result.files.slice(0, limit).map((h, i) => (
                    <ResultRow
                      key={h.file.id}
                      to={`/datasets/${h.dataset.id}/files/${h.file.id}`}
                      first={i === 0}
                      icon={<FileBadge type={h.file.type} />}
                      title={<Highlight text={h.file.name} query={q} />}
                      snippet={h.snippet ? <Highlight text={`…${h.snippet}…`} query={q} strong /> : undefined}
                      meta={`${h.dataset.name} · ${hitLabel(h)} · ${h.file.size} · ${h.file.updatedAt}`}
                      action="打开"
                    />
                  ))}
                </ResultGroup>
              )}

              {show('conversation') && result.conversations.length > 0 && (
                <ResultGroup label="对话" count={result.conversations.length} more={scope === 'all' && result.conversations.length > limit ? () => set({ scope: 'conversation' }) : undefined}>
                  {result.conversations.slice(0, limit).map((h) => (
                    <ResultRow
                      key={h.conversation.id}
                      onClick={() => navigate(`/chat/${h.conversation.id}`)}
                      icon={
                        <span className="flex size-[30px] items-center justify-center rounded-[8px] bg-soft text-text2">
                          <MessageSquare aria-hidden className="size-[13.5px]" />
                        </span>
                      }
                      title={<Highlight text={h.conversation.title} query={q} />}
                      snippet={<Highlight text={`最近提问：${h.conversation.lastQuestion}`} query={q} strong />}
                      meta={`${h.conversation.model} · ${h.conversation.rounds} 轮 · ${h.conversation.updatedAt}`}
                      action="继续"
                    />
                  ))}
                </ResultGroup>
              )}

              {scope === 'dataset' &&
                result.datasets.map((h) => <DatasetHitCard key={h.dataset.id} hit={h} query={q} className="mb-2.5" />)}
              {scope === 'file' && result.files.length === 0 && <p className="text-[12px] text-muted">当前范围内没有文件结果。</p>}
              {scope === 'conversation' && result.conversations.length === 0 && <p className="text-[12px] text-muted">当前范围内没有对话结果。</p>}
            </>
          )}
        </div>

        <aside aria-label="搜索辅助" className="flex w-[248px] shrink-0 flex-col gap-[22px]">
          {q && !empty && scope === 'all' && result.datasets.length > 0 && (
            <div className="flex flex-col gap-2.5">
              <SectionLabel label="知识库" count={result.datasets.length} />
              {result.datasets.slice(0, 3).map((h) => (
                <DatasetHitCard key={h.dataset.id} hit={h} query={q} />
              ))}
            </div>
          )}
          <div className="flex flex-col">
            <SectionLabel
              label="最近搜索"
              action={
                recent.length > 0 && (
                  <button
                    type="button"
                    onClick={() => {
                      clearRecentSearches();
                      setRecent([]);
                    }}
                    className="text-text2 hover:text-ink"
                  >
                    清除
                  </button>
                )
              }
            />
            <div className="h-2" />
            {recent.length === 0 && <p className="py-[7px] text-[12px] text-faint">暂无搜索记录</p>}
            {recent.map((r) => (
              <button key={r} type="button" onClick={() => submit(r)} className="flex items-center gap-2 py-[7px] text-left text-[12px] text-text2 hover:text-ink">
                <Clock aria-hidden className="size-3 text-muted" />
                <span className="truncate">{r}</span>
              </button>
            ))}
          </div>
          <div className="flex flex-col gap-2 rounded-xl bg-soft px-3.5 py-3">
            <p className="flex items-center gap-1.5 text-[12px] font-medium text-ink">
              <Info aria-hidden className="size-3 text-text2" />
              搜索范围
            </p>
            <p className="text-[11px] leading-[18px] text-text2">按名称匹配文件、对话与知识库；AI 摘要会检索文件内容并附上来源片段。</p>
            <div className="flex flex-col gap-1.5 pt-1 text-[11px] text-muted">
              {[
                ['⌘K', '任意页面唤起搜索'],
                ['↑ ↓', '切换结果'],
                ['⌘ ↵', '向知识库提问'],
              ].map(([k, v]) => (
                <p key={k} className="flex items-center gap-2">
                  <Kbd>{k}</Kbd>
                  {v}
                </p>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </PageColumn>
  );
}

interface FilterSelectProps {
  label: string;
  value: string;
  display: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  onClear?: () => void;
}

/** 筛选下拉：生效时深色描边 + 清除按钮（B5「知识库 产品知识库 ×」） */
function FilterSelect({ label, value, display, options, onChange, onClear }: FilterSelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);
  const active = !!onClear;

  return (
    <div ref={ref} className="relative">
      <div className={cn('flex items-center rounded-[7px] border text-[11.5px]', active ? 'border-ink bg-ink/[0.06]' : 'border-line bg-white hover:bg-soft')}>
        <button type="button" aria-haspopup="listbox" aria-expanded={open} aria-label={`${label}：${display}`} onClick={() => setOpen((v) => !v)} className={cn('flex items-center gap-[5px] py-1.5 pl-2.5', active ? 'pr-1' : 'pr-2')}>
          <span className="text-muted">{label}</span>
          <span className={active ? 'font-medium text-ink' : 'text-ink'}>{display}</span>
          {!active && <ChevronDown aria-hidden className="size-2.5 text-muted" />}
        </button>
        {active && (
          <button type="button" aria-label={`清除${label}筛选`} onClick={onClear} className="py-1.5 pr-2 pl-0.5 text-text2 hover:text-ink">
            <X className="size-2.5" />
          </button>
        )}
      </div>
      {open && (
        <div role="listbox" aria-label={label} className="absolute top-full right-0 z-40 mt-1.5 min-w-[140px] rounded-[10px] border border-line bg-white p-1 shadow-pop">
          {options.map((o) => (
            <button
              key={o.value}
              role="option"
              type="button"
              aria-selected={o.value === value}
              onClick={() => {
                onChange(o.value);
                setOpen(false);
              }}
              className="flex h-8 w-full items-center gap-2 rounded-[7px] px-2.5 text-left text-[12.5px] whitespace-nowrap text-ink hover:bg-soft"
            >
              <span className="flex-1">{o.label}</span>
              {o.value === value && <Check aria-hidden className="size-3.5 text-text2" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ResultGroup({ label, count, more, children }: { label: string; count: number; more?: () => void; children: ReactNode }) {
  return (
    <section aria-label={label} className="mb-3 flex flex-col">
      <SectionLabel
        label={label}
        count={count}
        action={
          more && (
            <button type="button" onClick={more} className="flex items-center gap-1 text-text2 hover:text-ink">
              查看全部
              <ArrowRight aria-hidden className="size-2.5" />
            </button>
          )
        }
      />
      <div className="h-2.5" />
      {children}
    </section>
  );
}

interface ResultRowProps {
  icon: ReactNode;
  title: ReactNode;
  snippet?: ReactNode;
  meta: string;
  action: string;
  to?: string;
  onClick?: () => void;
  first?: boolean;
}

/** 结果行：首条浅灰底（设计稿中的默认选中态），悬停同样高亮 */
function ResultRow({ icon, title, snippet, meta, action, to, onClick, first }: ResultRowProps) {
  const cls = cn('group flex w-full items-center gap-3 rounded-[10px] py-2 pr-3 pl-2.5 text-left transition-colors hover:bg-soft', first && 'bg-soft');
  const body = (
    <>
      {icon}
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="truncate text-[13px] font-medium text-ink">{title}</span>
        {snippet && <span className="truncate text-[11.5px] text-text2">{snippet}</span>}
        <span className="truncate text-[10.5px] text-muted">{meta}</span>
      </span>
      <span className={cn('flex shrink-0 items-center gap-1 text-[11.5px] group-hover:text-ink', first ? 'text-ink' : 'text-muted')}>
        {action}
        <ArrowRight aria-hidden className="size-2.5" />
      </span>
    </>
  );
  return to ? (
    <Link to={to} className={cls}>
      {body}
    </Link>
  ) : (
    <button type="button" onClick={onClick} className={cls}>
      {body}
    </button>
  );
}

function DatasetHitCard({ hit, query, className }: { hit: ReturnType<typeof search>['datasets'][number]; query: string; className?: string }) {
  const d = hit.dataset;
  return (
    <Link to={`/datasets/${d.id}`} className={cn('flex flex-col gap-1.5 rounded-xl border border-line bg-white px-3 py-[11px] shadow-[0_3px_10px_0_rgba(0,0,0,0.04)] hover:border-dash', className)}>
      <span className="flex items-center gap-2">
        <span className="flex size-[22px] items-center justify-center rounded-[6px] bg-soft text-text2">
          <Database aria-hidden className="size-2.5" />
        </span>
        <span className="flex-1 truncate text-[12.5px] font-medium text-ink">
          <Highlight text={d.name} query={query} />
        </span>
        <Chip tone={d.status === 'enabled' ? 'green' : 'gray'}>{d.status === 'enabled' ? '已启用' : '已停用'}</Chip>
      </span>
      <span className="truncate text-[11px] text-text2">
        <Highlight text={d.description} query={query} strong />
      </span>
      <span className="text-[10.5px] text-muted">{hit.files.toLocaleString('en-US')} 个文件 · 进入 →</span>
    </Link>
  );
}

function EmptyPrompt() {
  return (
    <div className="flex flex-col items-center gap-2.5 rounded-2xl border border-dashed border-dash px-8 pt-11 pb-10">
      <span className="flex size-11 items-center justify-center rounded-xl bg-soft text-text2">
        <Search aria-hidden className="size-5" />
      </span>
      <p className="mt-1 text-[15px] font-medium text-ink">搜索文件、对话与知识库</p>
      <p className="text-[12px] text-muted">输入关键词后按回车；在任意页面按 ⌘K 也可以快速搜索。</p>
    </div>
  );
}

interface NoResultsProps {
  query: string;
  scopeText: string;
  hasFilters: boolean;
  onClearFilters: () => void;
  onAsk: () => void;
  onUpload: () => void;
}

/** B5 无结果：建议 + 清空筛选 / 用关键词新建对话 + 上传提示 + 你可能在找 */
function NoResults({ query, scopeText, hasFilters, onClearFilters, onAsk, onUpload }: NoResultsProps) {
  const s = suggestions();
  return (
    <>
      <div className="flex flex-col items-center gap-2.5 rounded-2xl border border-dashed border-dash px-8 pt-11 pb-10">
        <span className="flex size-11 items-center justify-center rounded-xl bg-soft text-text2">
          <Search aria-hidden className="size-5" />
        </span>
        <p className="mt-1 text-center text-[15px] font-medium text-ink">没有找到与「{query}」相关的内容</p>
        <p className="text-[12px] text-muted">当前范围：{scopeText}</p>
        <ul className="mt-2 flex w-[360px] max-w-full flex-col gap-[7px] rounded-xl bg-soft px-4 py-3 text-[12px] text-text2">
          {['检查关键词是否有错别字', '缩短关键词，或换一种说法', '把范围扩大到全部知识库'].map((t) => (
            <li key={t} className="flex items-center gap-2">
              <span aria-hidden className="text-[13px] font-medium text-muted">
                ·
              </span>
              {t}
            </li>
          ))}
        </ul>
        <div className="mt-2.5 flex flex-wrap justify-center gap-2.5">
          {hasFilters && (
            <Button variant="secondary" icon={<X className="size-3" />} onClick={onClearFilters}>
              清空筛选
            </Button>
          )}
          <Button icon={<Plus className="size-3" />} onClick={onAsk} className="max-w-[320px]">
            <span className="truncate">用「{query}」新建对话</span>
          </Button>
        </div>
      </div>

      <div className="mt-6 flex items-center gap-3 rounded-[14px] border border-line bg-white px-4 py-3.5">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-[7px] bg-ink text-white">
          <Sparkles aria-hidden className="size-[12.6px]" />
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="text-[12.5px] font-medium text-ink">知识库中也没有检索到相关片段</span>
          <span className="text-[11.5px] text-muted">如果资料还没上传，可以先上传到知识库再提问。</span>
        </span>
        <Button variant="secondary" icon={<Upload className="size-3" />} onClick={onUpload}>
          上传资料
        </Button>
      </div>

      <SectionLabel label="你可能在找" className="mt-6 mb-2.5" />
      {s.conversation && (
        <ResultRow
          onClick={onAsk}
          icon={
            <span className="flex size-[30px] items-center justify-center rounded-[8px] bg-soft text-text2">
              <MessageSquare aria-hidden className="size-[13.5px]" />
            </span>
          }
          title={s.conversation.title}
          meta={`对话 · ${s.conversation.updatedAt}`}
          action="打开"
        />
      )}
      {s.file && s.dataset && (
        <ResultRow
          to={`/datasets/${s.dataset.id}/files/${s.file.id}`}
          icon={
            <span className="flex size-[30px] items-center justify-center rounded-[8px] bg-soft text-text2">
              <FileText aria-hidden className="size-[13.5px]" />
            </span>
          }
          title={s.file.name}
          meta={`文件 · ${s.dataset.name} · ${s.file.updatedAt}`}
          action="打开"
        />
      )}
    </>
  );
}
