import { ArrowRight, Clock, Cpu, Database, MessageSquare, Plus, Search, Sparkles, Upload } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';

import { FileBadge } from '@/components/FileBadge';
import { Kbd } from '@/components/ui/Kbd';
import { cn } from '@/lib/cn';
import {
  hitLabel,
  pageTotalOf,
  pushRecentSearch,
  QUERY_MAX,
  recentSearches,
  recentVisits,
  search,
  type ConversationHit,
  type DatasetHit,
  type FileHit,
  type RecentVisit,
} from '@/services/search';

import { Highlight } from './Highlight';

type Scope = 'all' | 'file' | 'conversation' | 'dataset' | 'action';

type Item =
  | { kind: 'file'; key: string; hit: FileHit }
  | { kind: 'conversation'; key: string; hit: ConversationHit }
  | { kind: 'dataset'; key: string; hit: DatasetHit }
  | { kind: 'action'; key: string; id: 'ask' | 'new-chat' | 'upload' | 'models'; title: ReactNode; sub?: string }
  | { kind: 'recent'; key: string; text: string }
  | { kind: 'visit'; key: string; visit: RecentVisit };

const scopeLabel: Record<Scope, string> = { all: '全部', file: '文件', conversation: '对话', dataset: '知识库', action: '操作' };
const SCOPES = Object.keys(scopeLabel) as Scope[];

/**
 * 快速搜索（⌘K，B6 / B7）：浮层按右侧内容面板居中。
 * 无关键词时单栏展示最近搜索、最近访问与快捷操作；输入后展开为「结果 + 预览」双栏。
 */
export function CommandPalette({ initialQuery, onClose }: { initialQuery: string; onClose: () => void }) {
  const navigate = useNavigate();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState(initialQuery);
  const [scope, setScope] = useState<Scope>('all');
  const [active, setActive] = useState(0);
  const q = query.trim();
  const result = useMemo(() => search(q), [q]);

  const actions: Item[] = useMemo(
    () =>
      q
        ? [
            { kind: 'action', key: 'a-ask', id: 'ask', title: <>向知识库提问「<Highlight text={q} query={q} />」</>, sub: '在新对话中检索全部已启用的知识库' },
            { kind: 'action', key: 'a-new', id: 'new-chat', title: '新建对话' },
            { kind: 'action', key: 'a-up', id: 'upload', title: '上传资料' },
          ]
        : [
            { kind: 'action', key: 'a-new', id: 'new-chat', title: '新建对话' },
            { kind: 'action', key: 'a-up', id: 'upload', title: '上传资料到知识库' },
            { kind: 'action', key: 'a-models', id: 'models', title: '检查模型配置' },
          ],
    [q],
  );

  /** 分组：最佳匹配（首个文件）→ 文件 → 对话 → 知识库 → 操作；无关键词时展示最近搜索 / 最近访问 / 快捷操作 */
  const groups = useMemo(() => {
    if (!q) {
      return [
        { label: '最近搜索', items: recentSearches().map<Item>((text) => ({ kind: 'recent', key: `r-${text}`, text })) },
        { label: '最近访问', items: recentVisits().map<Item>((visit, i) => ({ kind: 'visit', key: `v-${i}`, visit })) },
        { label: '快捷操作', items: actions },
      ].filter((g) => g.items.length);
    }
    const files = result.files.slice(0, 4).map<Item>((hit) => ({ kind: 'file', key: `f-${hit.file.id}`, hit }));
    const convs = result.conversations.slice(0, 3).map<Item>((hit) => ({ kind: 'conversation', key: `c-${hit.conversation.id}`, hit }));
    const dss = result.datasets.slice(0, 3).map<Item>((hit) => ({ kind: 'dataset', key: `d-${hit.dataset.id}`, hit }));
    const by: Record<Exclude<Scope, 'all'>, Item[]> = { file: files, conversation: convs, dataset: dss, action: actions };
    if (scope !== 'all') return [{ label: scopeLabel[scope], items: by[scope] }];
    return [
      { label: '最佳匹配', items: files.slice(0, 1) },
      { label: '文件', items: files.slice(1) },
      { label: '对话', items: convs },
      { label: '知识库', items: dss },
      { label: '操作', items: actions },
    ].filter((g) => g.items.length);
  }, [q, result, scope, actions]);

  const flat = groups.flatMap((g) => g.items);
  const counts: Record<Scope, number> = {
    file: result.files.length,
    conversation: result.conversations.length,
    dataset: result.datasets.length,
    action: q ? actions.length : 0,
    all: 0,
  };
  counts.all = counts.file + counts.conversation + counts.dataset;
  const current = flat[Math.min(active, flat.length - 1)];

  useEffect(() => setActive(0), [q, scope]);
  useEffect(() => {
    inputRef.current?.focus();
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);
  useEffect(() => {
    document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: 'nearest' });
  }, [active, listId]);

  const go = (to: string) => {
    if (q) pushRecentSearch(q);
    onClose();
    navigate(to);
  };
  /** 提问 / 新建对话：带着问题进入 F1，由用户选择知识库后发送 */
  const chat = (question?: string) => {
    if (q) pushRecentSearch(q);
    onClose();
    navigate('/chat', { state: question ? { question } : undefined });
  };

  const run = (item: Item | undefined, ask = false) => {
    if (ask || item?.kind === 'action') {
      const id = ask ? 'ask' : item?.kind === 'action' ? item.id : 'ask';
      if (id === 'upload') return go('/datasets');
      if (id === 'models') return go('/models');
      return chat(id === 'ask' ? q : undefined);
    }
    if (!item) return;
    if (item.kind === 'recent') return setQuery(item.text);
    if (item.kind === 'visit') {
      const v = item.visit;
      if (v.kind === 'file') return go(`/datasets/${v.dataset.id}/files/${v.file.id}`);
      if (v.kind === 'dataset') return go(`/datasets/${v.dataset.id}`);
      return go(`/chat/${v.conversation.id}`);
    }
    if (item.kind === 'file') return go(`/datasets/${item.hit.dataset.id}/files/${item.hit.file.id}`);
    if (item.kind === 'dataset') return go(`/datasets/${item.hit.dataset.id}`);
    if (item.kind === 'conversation') return go(`/chat/${item.hit.conversation.id}`);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => (flat.length ? (i + 1) % flat.length : 0));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => (flat.length ? (i - 1 + flat.length) % flat.length : 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      run(current, (e.metaKey || e.ctrlKey) && !!q);
    } else if (e.key === 'Tab' && q) {
      e.preventDefault();
      const i = SCOPES.indexOf(scope);
      setScope(SCOPES[(i + (e.shiftKey ? SCOPES.length - 1 : 1)) % SCOPES.length]);
    }
  };

  let idx = -1;
  const renderGroup = (g: (typeof groups)[number]) => {
    // 最近搜索以标签形式横向排列，其余分组为列表行
    const chips = g.label === '最近搜索';
    return (
      <div key={g.label} role="group" aria-label={g.label}>
        <p className="pt-2.5 pb-1 pl-2.5 text-[10.5px] text-muted">{g.label}</p>
        <div className={cn(chips && 'flex flex-wrap gap-2 px-2.5 pt-0.5 pb-2')}>
          {g.items.map((item) => {
            idx += 1;
            const i = idx;
            const props = { key: item.key, id: `${listId}-${i}`, selected: i === active, onHover: () => setActive(i), onClick: () => run(item) };
            return chips && item.kind === 'recent' ? (
              <Chip {...props} text={item.text} />
            ) : (
              <Row {...props} item={item} query={q} best={g.label === '最佳匹配'} />
            );
          })}
        </div>
      </div>
    );
  };

  return createPortal(
    // 左右留白与 AppLayout 一致（侧栏 216 + 间距 13 / 右侧 12），使浮层落在内容面板的中线上
    <div className="fixed inset-0 z-50 flex justify-center bg-[rgba(29,29,27,0.28)] pt-[10vh] pr-[36px] pl-[253px]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="快速搜索"
        onKeyDown={onKeyDown}
        className="flex h-fit max-h-[80vh] w-[min(760px,100%)] flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-[0_20px_60px_0_rgba(0,0,0,0.18)]"
      >
        <div className="flex h-[60px] shrink-0 items-center gap-3 pr-4 pl-5">
          <Search aria-hidden className="size-[17px] text-ink" />
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded
            aria-controls={listId}
            aria-activedescendant={flat.length ? `${listId}-${active}` : undefined}
            aria-label="搜索文件、对话与知识库"
            value={query}
            maxLength={QUERY_MAX}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索文件、对话与知识库，或直接提问…"
            className="min-w-0 flex-1 bg-transparent text-[15px] text-ink placeholder:text-muted"
          />
          {q && <span className="shrink-0 text-[11px] text-muted">{counts.all} 个结果</span>}
          <Kbd className="bg-white">ESC</Kbd>
        </div>

        {q ? (
          <div className="flex shrink-0 items-center gap-5 border-y border-divider px-5" role="tablist" aria-label="搜索范围">
            {SCOPES.map((s) => (
              <button
                key={s}
                type="button"
                role="tab"
                aria-selected={scope === s}
                onClick={() => setScope(s)}
                className={cn(
                  '-mb-px flex items-center gap-1 border-b-2 pt-2.5 pb-2 text-[12px] leading-none',
                  scope === s ? 'border-ink font-medium text-ink' : 'border-transparent text-text2 hover:text-ink',
                )}
              >
                {scopeLabel[s]}
                <span className="font-num text-[10.5px] text-muted">{counts[s]}</span>
              </button>
            ))}
            <span className="ml-auto text-[10.5px] text-faint">Tab 切换</span>
          </div>
        ) : (
          <div className="h-px shrink-0 bg-divider" />
        )}

        <div className="flex min-h-0 flex-1">
          <div id={listId} role="listbox" aria-label="搜索结果" className={cn('flex min-w-0 flex-col overflow-y-auto px-2.5 pt-1.5 pb-2.5', q ? 'w-[452px] shrink-0 px-2' : 'flex-1')}>
            {q && counts.all === 0 && scope !== 'action' && (
              <p className="px-2.5 pt-4 pb-2 text-[12px] text-muted">没有找到与「{q}」相关的文件、对话或知识库</p>
            )}
            {groups.map(renderGroup)}
          </div>
          {q && (
            <>
              <div className="w-px shrink-0 self-stretch bg-divider" />
              <div className="flex min-w-0 flex-1 flex-col overflow-y-auto bg-[#fafaf8] px-[18px] py-4">
                <Preview item={current} query={q} onOpen={() => run(current)} onAsk={() => run(current, true)} />
              </div>
            </>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-3.5 bg-soft px-[18px] py-2.5 text-[11px] text-muted">
          <span className="flex items-center gap-1.5">
            <Kbd className="bg-white">↑ ↓</Kbd>选择
          </span>
          <span className="flex items-center gap-1.5">
            <Kbd className="bg-white">↵</Kbd>打开
          </span>
          <span className="flex items-center gap-1.5">
            <Kbd className="bg-white">⌘ ↵</Kbd>提问
          </span>
          {q ? (
            counts.all > 0 && (
              <button type="button" onClick={() => go(`/search?q=${encodeURIComponent(q)}`)} className="ml-auto flex items-center gap-1 text-[11.5px] font-medium text-ink hover:underline">
                查看全部 {counts.all} 个结果
                <ArrowRight aria-hidden className="size-[11px]" />
              </button>
            )
          ) : (
            <span className="ml-auto">输入关键词，或按 ⌘ ↵ 直接向知识库提问</span>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** 最近搜索标签：点击填入关键词 */
function Chip({ id, text, selected, onHover, onClick }: { id: string; text: string; selected: boolean; onHover: () => void; onClick: () => void }) {
  return (
    <div
      id={id}
      role="option"
      aria-selected={selected}
      onMouseMove={onHover}
      onClick={onClick}
      className={cn('flex cursor-pointer items-center gap-1.5 rounded-full px-2.5 py-[5px] text-[12px] text-text2', selected ? 'bg-active text-ink' : 'bg-soft')}
    >
      <Clock aria-hidden className="size-[11px] text-muted" />
      {text}
    </div>
  );
}

function IconBox({ children, dark }: { children: ReactNode; dark?: boolean }) {
  return (
    <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-[7px] [&>svg]:size-[12.6px]', dark ? 'bg-ink text-white' : 'bg-soft text-text2')}>{children}</span>
  );
}

function Row({ id, item, query, selected, best, onHover, onClick }: { id: string; item: Item; query: string; selected: boolean; best: boolean; onHover: () => void; onClick: () => void }) {
  let icon: ReactNode;
  let title: ReactNode;
  let sub: ReactNode = null;
  let trailing: ReactNode = null;

  switch (item.kind) {
    case 'file':
      icon = <FileBadge type={item.hit.file.type} className="size-7" />;
      title = <Highlight text={item.hit.file.name} query={query} />;
      sub = best ? `${item.hit.dataset.name} · ${hitLabel(item.hit)} · ${item.hit.file.size}` : `${item.hit.dataset.name} · ${item.hit.file.updatedAt}`;
      break;
    case 'conversation':
      icon = (
        <IconBox>
          <MessageSquare />
        </IconBox>
      );
      title = <Highlight text={item.hit.conversation.title} query={query} />;
      sub = `${item.hit.conversation.model} · ${item.hit.conversation.rounds} 轮 · ${item.hit.conversation.updatedAt}`;
      break;
    case 'dataset':
      icon = (
        <IconBox>
          <Database />
        </IconBox>
      );
      title = item.hit.dataset.name;
      sub = `${item.hit.dataset.description}${item.hit.dataset.status === 'disabled' ? ' · 已停用' : ''}`;
      break;
    case 'action':
      icon = <IconBox dark={item.id === 'ask'}>{{ ask: <Sparkles />, upload: <Upload />, models: <Cpu />, 'new-chat': <Plus /> }[item.id]}</IconBox>;
      title = item.title;
      sub = item.sub;
      if (item.id === 'ask') trailing = <Kbd>⌘ ↵</Kbd>;
      break;
    case 'recent':
      icon = (
        <IconBox>
          <Clock />
        </IconBox>
      );
      title = item.text;
      break;
    case 'visit': {
      const v = item.visit;
      trailing = <span className="font-num text-[11px] font-medium text-muted">{v.at}</span>;
      if (v.kind === 'file') {
        icon = <FileBadge type={v.file.type} className="size-7" />;
        title = v.file.name;
        sub = `${v.dataset.name} · 文件`;
      } else if (v.kind === 'dataset') {
        icon = (
          <IconBox>
            <Database />
          </IconBox>
        );
        title = v.dataset.name;
        sub = `知识库 · ${v.files} 个文件`;
      } else {
        icon = (
          <IconBox>
            <MessageSquare />
          </IconBox>
        );
        title = v.conversation.title;
        sub = `对话${v.dataset ? ` · ${v.dataset.name}` : ''}`;
      }
      break;
    }
  }

  return (
    <div
      id={id}
      role="option"
      aria-selected={selected}
      onMouseMove={onHover}
      onClick={onClick}
      className={cn('flex w-full cursor-pointer items-center gap-[11px] rounded-[9px] px-2.5 py-2 text-left', selected && 'bg-page')}
    >
      {icon}
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-[12.5px] font-medium text-ink">{title}</span>
        {sub && <span className="truncate text-[10.5px] text-muted">{sub}</span>}
      </span>
      {!(selected && item.kind === 'visit') && trailing}
      {selected && (!trailing || item.kind === 'visit') && (
        <span className="flex items-center gap-1.5 text-[11px] text-text2">
          打开 <Kbd>↵</Kbd>
        </span>
      )}
    </div>
  );
}

function MetaRows({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="flex flex-col gap-1.5 rounded-lg border border-divider bg-white p-3 text-[12px]">
      {rows.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <dt className="w-7 shrink-0 text-muted">{k}</dt>
          <dd className="min-w-0 text-ink">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function PreviewActions({ primary, secondary, onPrimary, onSecondary }: { primary: string; secondary: string; onPrimary: () => void; onSecondary: () => void }) {
  return (
    <div className="flex gap-2">
      <button type="button" onClick={onPrimary} className="flex-1 rounded-lg bg-ink px-3 py-[7px] text-[12px] font-medium text-white hover:bg-[#33332f]">
        {primary}
      </button>
      <button type="button" onClick={onSecondary} className="flex-1 rounded-lg border border-line bg-white px-3 py-[7px] text-[12px] font-medium text-text2 hover:bg-soft">
        {secondary}
      </button>
    </div>
  );
}

/** 右侧预览：文件展示状态与内容命中；对话 / 知识库展示摘要信息 */
function Preview({ item, query, onOpen, onAsk }: { item?: Item; query: string; onOpen: () => void; onAsk: () => void }) {
  const head = (icon: ReactNode, title: ReactNode, sub: string) => (
    <div className="flex items-center gap-2.5">
      {icon}
      <div className="flex min-w-0 flex-col gap-[3px]">
        <p className="truncate text-[14px] font-medium text-ink">{title}</p>
        <p className="truncate text-[11px] text-muted">{sub}</p>
      </div>
    </div>
  );

  if (!item || item.kind === 'recent' || item.kind === 'action' || item.kind === 'visit') {
    return (
      <div className="flex h-full flex-col gap-3">
        <p className="text-[11px] font-medium text-muted">提示</p>
        <p className="text-[12px] leading-[18px] text-text2">按名称匹配文件、对话与知识库；按 ⌘ ↵ 可直接向知识库提问，回答会附带来源片段。</p>
      </div>
    );
  }

  if (item.kind === 'file') {
    const { file, dataset, passages, titleHit, contentHits } = item.hit;
    const status = file.status === 'done' ? `已完成 · ${file.chunkCount} 个分块` : file.status === 'failed' ? '解析失败' : `解析中 ${file.progressEstimated ? '≈' : ''}${file.progress}%`;
    return (
      <div className="flex flex-col gap-3">
        <p className="text-[11px] font-medium text-muted">预览</p>
        {head(<FileBadge type={file.type} className="size-9 rounded-lg text-[10px]" />, file.name, `${dataset.name} · ${file.size} · ${pageTotalOf(file)} 页`)}
        <MetaRows
          rows={[
            ['状态', status],
            ['更新', file.updatedAt],
            ['命中', [titleHit && '标题 1 处', contentHits > 0 && `内容 ${contentHits} 处`].filter(Boolean).join(' · ')],
          ]}
        />
        {passages.length > 0 && (
          <>
            <p className="text-[11px] font-medium text-muted">内容命中</p>
            {passages.slice(0, 2).map((p) => (
              <div key={p.page} className="flex flex-col gap-1 rounded-md border border-divider bg-white px-2.5 py-2">
                <p className="text-[11px] font-medium text-muted">第 {p.page} 页</p>
                <p className="text-[12px] leading-[18px] text-text2">
                  <Highlight text={p.text} query={query} strong />
                </p>
              </div>
            ))}
          </>
        )}
        <PreviewActions primary="打开文件 ↵" secondary="基于此文件提问" onPrimary={onOpen} onSecondary={onAsk} />
      </div>
    );
  }

  if (item.kind === 'conversation') {
    const c = item.hit.conversation;
    return (
      <div className="flex flex-col gap-3">
        <p className="text-[11px] font-medium text-muted">预览</p>
        {head(
          <IconBox>
            <MessageSquare />
          </IconBox>,
          <Highlight text={c.title} query={query} />,
          `${item.hit.dataset?.name ?? '全部知识库'} · ${c.updatedAt}`,
        )}
        <MetaRows
          rows={[
            ['模型', c.model],
            ['轮数', `${c.rounds} 轮`],
            ['引用', `${c.citedDocs} 份文档 · ${c.citedChunks} 个片段`],
          ]}
        />
        <p className="text-[11px] font-medium text-muted">最近提问</p>
        <p className="rounded-md border border-divider bg-white px-2.5 py-2 text-[12px] leading-[18px] text-text2">{c.lastQuestion}</p>
        <PreviewActions primary="继续对话 ↵" secondary="新建对话" onPrimary={onOpen} onSecondary={onAsk} />
      </div>
    );
  }

  const d = item.hit.dataset;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[11px] font-medium text-muted">预览</p>
      {head(
        <IconBox>
          <Database />
        </IconBox>,
        d.name,
        d.description,
      )}
      <MetaRows
        rows={[
          ['状态', d.status === 'enabled' ? '已启用' : '已停用'],
          ['文件', `${item.hit.files} 个`],
          ['更新', d.updatedAt],
        ]}
      />
      <PreviewActions primary="进入知识库 ↵" secondary="向此知识库提问" onPrimary={onOpen} onSecondary={onAsk} />
    </div>
  );
}
