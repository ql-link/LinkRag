import { Bold, Code, ExternalLink, Italic, Link2, Strikethrough, Trash2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/cn';

import { wrapSelection } from './AutoTextarea';

export interface Selection {
  el: HTMLTextAreaElement;
  start: number;
  end: number;
  apply: (text: string) => void;
}

const btn = 'flex size-7 items-center justify-center rounded-[6px] text-text2 hover:bg-soft hover:text-ink';

/** 设计稿 C8：选中文字后的浮动格式栏（粗体 / 斜体 / 删除线 / 行内代码 / 链接） */
export function FormatBar({ sel, onDone }: { sel: Selection; onDone: () => void }) {
  const [linking, setLinking] = useState(false);
  const barRef = useRef<HTMLDivElement>(null);

  // 点击格式栏与当前文本域以外的位置时收起
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!barRef.current?.contains(t) && !sel.el.contains(t)) onDone();
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [sel.el, onDone]);
  const [url, setUrl] = useState('');
  const text = sel.el.value;
  const selected = text.slice(sel.start, sel.end);
  const existing = /^\[([^\]]*)\]\(([^)]*)\)$/.exec(selected);

  useEffect(() => {
    setLinking(false);
    setUrl(existing?.[2] ?? '');
  }, [sel.el, sel.start, sel.end]); // eslint-disable-line react-hooks/exhaustive-deps

  const commit = (next: { text: string; start: number; end: number }) => {
    sel.apply(next.text);
    requestAnimationFrame(() => {
      sel.el.focus();
      sel.el.setSelectionRange(next.start, next.end);
    });
    onDone();
  };
  const wrap = (a: string, b = a) => commit(wrapSelection(text, sel.start, sel.end, a, b));
  const applyLink = (remove = false) => {
    const label = existing ? existing[1] : selected;
    const md = remove || !url.trim() ? label : `[${label}](${url.trim()})`;
    commit({ text: text.slice(0, sel.start) + md + text.slice(sel.end), start: sel.start, end: sel.start + md.length });
  };

  const rect = sel.el.getBoundingClientRect();
  const zoom = Number(getComputedStyle(document.body).zoom) || 1;
  const style = { top: Math.max(8, rect.top / zoom - 44), left: rect.left / zoom };

  return (
    <div ref={barRef} data-editor-keep role="toolbar" aria-label="文字格式" style={style} onMouseDown={(e) => e.target instanceof HTMLInputElement || e.preventDefault()} className="fixed z-40 flex flex-col gap-1.5">
      <div className="flex items-center gap-0.5 rounded-[9px] border border-line bg-white p-1 shadow-toast">
        <button type="button" className={btn} title="粗体 ⌘B" aria-label="粗体" onClick={() => wrap('**')}>
          <Bold className="size-3.5" />
        </button>
        <button type="button" className={btn} title="斜体 ⌘I" aria-label="斜体" onClick={() => wrap('*')}>
          <Italic className="size-3.5" />
        </button>
        <button type="button" className={btn} title="删除线" aria-label="删除线" onClick={() => wrap('~~')}>
          <Strikethrough className="size-3.5" />
        </button>
        <button type="button" className={btn} title="行内代码" aria-label="行内代码" onClick={() => wrap('`')}>
          <Code className="size-3.5" />
        </button>
        <span className="mx-0.5 h-4 w-px bg-line" />
        <button type="button" className={cn(btn, linking && 'bg-active text-ink')} title="链接 ⌘K" aria-label="链接" aria-expanded={linking} onClick={() => setLinking((v) => !v)}>
          <Link2 className="size-3.5" />
        </button>
      </div>
      {linking && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            applyLink();
          }}
          className="flex w-[360px] items-center gap-1.5 rounded-[10px] border border-line bg-white p-1.5 shadow-dialog"
        >
          <Link2 aria-hidden className="ml-1 size-3.5 shrink-0 text-muted" />
          <input autoFocus value={url} onChange={(e) => setUrl(e.target.value)} placeholder="粘贴或输入链接地址" aria-label="链接地址" className="min-w-0 flex-1 text-[12px] text-ink outline-none" />
          {url.trim() && (
            <a href={url} target="_blank" rel="noreferrer" aria-label="打开链接" className="text-muted hover:text-ink">
              <ExternalLink className="size-3.5" />
            </a>
          )}
          {existing && (
            <button type="button" aria-label="移除链接" onClick={() => applyLink(true)} className="text-muted hover:text-red">
              <Trash2 className="size-3.5" />
            </button>
          )}
          <button type="submit" className="rounded-[6px] bg-active px-2.5 py-1 text-[11.5px] font-medium text-ink hover:bg-dash">
            应用
          </button>
        </form>
      )}
    </div>
  );
}
