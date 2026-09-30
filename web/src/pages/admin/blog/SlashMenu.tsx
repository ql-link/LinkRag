import { AlertCircle, Code, Heading1, Heading2, Heading3, Minus, ImageIcon, List, ListOrdered, Pilcrow, Quote, Table } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

import type { BlockInit } from './blocks';
import { blankBlock } from './editorOps';

interface Cmd {
  key: string;
  label: string;
  desc: string;
  hint: string;
  icon: ReactNode;
  words: string;
  make: () => BlockInit;
}

const ic = 'size-3.5';
export const COMMANDS: Cmd[] = [
  { key: 'p', label: '正文', desc: '普通段落', hint: '', icon: <Pilcrow className={ic} />, words: 'p text zhengwen 段落', make: () => blankBlock('p') },
  { key: 'h1', label: '一级标题', desc: '文章大标题', hint: '#', icon: <Heading1 className={ic} />, words: 'h1 heading biaoti 标题', make: () => blankBlock('h', { level: 1 }) },
  { key: 'h2', label: '二级标题', desc: '大节标题', hint: '##', icon: <Heading2 className={ic} />, words: 'h2 heading biaoti 标题', make: () => blankBlock('h', { level: 2 }) },
  { key: 'h3', label: '三级标题', desc: '小节标题', hint: '###', icon: <Heading3 className={ic} />, words: 'h3 heading biaoti 标题', make: () => blankBlock('h', { level: 3 }) },
  { key: 'ul', label: '无序列表', desc: '圆点列表', hint: '-', icon: <List className={ic} />, words: 'ul list liebiao', make: () => blankBlock('list') },
  { key: 'ol', label: '有序列表', desc: '编号列表', hint: '1.', icon: <ListOrdered className={ic} />, words: 'ol list liebiao number', make: () => blankBlock('list', { ordered: true }) },
  { key: 'code', label: '代码块', desc: '可选择语言', hint: '```', icon: <Code className={ic} />, words: 'code daima', make: () => blankBlock('code') },
  { key: 'quote', label: '引用', desc: '引述一段话', hint: '>', icon: <Quote className={ic} />, words: 'quote yinyong', make: () => blankBlock('quote') },
  { key: 'callout', label: '提示块', desc: '带标签的提示 / 注意', hint: '> **', icon: <AlertCircle className={ic} />, words: 'callout tip tishi note', make: () => blankBlock('callout') },
  { key: 'table', label: '表格', desc: '3 × 3 起步', hint: '|', icon: <Table className={ic} />, words: 'table biaoge grid', make: () => blankBlock('table') },
  { key: 'hr', label: '分隔线', desc: '水平分隔', hint: '---', icon: <Minus className={ic} />, words: 'hr divider fengexian line', make: () => blankBlock('hr') },
  { key: 'img', label: '图片', desc: '上传、粘贴或插入链接', hint: '![]', icon: <ImageIcon className={ic} />, words: 'image img tupian picture', make: () => blankBlock('img') },
];

export function matchCommands(query: string): Cmd[] {
  const q = query.trim().toLowerCase();
  if (!q) return COMMANDS;
  return COMMANDS.filter((c) => c.label.includes(q) || c.words.includes(q) || c.key.startsWith(q));
}

/** 设计稿 C7：段落中输入 `/` 唤起的插入菜单，↑↓ 选择 · ↵ 插入 · esc 关闭 */
export function SlashMenu({ anchor, query, onPick, onClose }: { anchor: HTMLElement; query: string; onPick: (b: BlockInit) => void; onClose: () => void }) {
  const items = useMemo(() => matchCommands(query), [query]);
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);
  useEffect(() => setActive(0), [query]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        setActive((a) => (items.length ? (a + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length : 0));
      } else if (e.key === 'Enter' && items[active]) {
        e.preventDefault();
        e.stopPropagation();
        onPick(items[active].make());
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    anchor.addEventListener('keydown', onKey, true);
    return () => anchor.removeEventListener('keydown', onKey, true);
  }, [anchor, items, active, onPick, onClose]);

  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  const rect = anchor.getBoundingClientRect();
  const zoom = Number(getComputedStyle(document.body).zoom) || 1;
  const below = rect.bottom / zoom + 320 < window.innerHeight / zoom;
  const style = below ? { top: rect.bottom / zoom + 6, left: rect.left / zoom } : { bottom: window.innerHeight / zoom - rect.top / zoom + 6, left: rect.left / zoom };

  return (
    <div style={style} className="fixed z-40 w-[280px] overflow-hidden rounded-[12px] border border-line bg-white shadow-dialog" onMouseDown={(e) => e.preventDefault()}>
      <p className="border-b border-divider px-3 py-2 text-[11px] text-muted">{query ? `匹配“${query}”` : '插入块'}</p>
      {items.length === 0 ? (
        <p className="px-3 py-5 text-center text-[12px] text-muted">没有匹配的块类型</p>
      ) : (
        <ul ref={listRef} role="listbox" aria-label="插入块" className="max-h-[260px] overflow-y-auto p-1">
          {items.map((c, i) => (
            <li key={c.key} role="option" aria-selected={i === active} data-active={i === active}>
              <button type="button" onMouseEnter={() => setActive(i)} onClick={() => onPick(c.make())} className={cn('flex w-full items-center gap-2.5 rounded-[8px] px-2 py-1.5 text-left', i === active && 'bg-soft')}>
                <span className="flex size-7 shrink-0 items-center justify-center rounded-[7px] border border-line bg-white text-text2">{c.icon}</span>
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="text-[12.5px] text-ink">{c.label}</span>
                  <span className="truncate text-[11px] text-muted">{c.desc}</span>
                </span>
                {c.hint && <span className="font-mono text-[10.5px] text-muted">{c.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="flex gap-3 border-t border-divider px-3 py-1.5 text-[10.5px] text-muted">
        <span>↑↓ 选择</span>
        <span>↵ 插入</span>
        <span>esc 关闭</span>
      </p>
    </div>
  );
}
