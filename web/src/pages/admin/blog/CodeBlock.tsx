import { Check, ChevronDown, Copy, Search } from 'lucide-react';
import { useEffect, useRef, useState, type KeyboardEvent } from 'react';

import { cn } from '@/lib/cn';

import { AutoTextarea } from './AutoTextarea';
import { focusAttr, type BlockCtx } from './blockCtx';
import type { EBlock } from './blocks';

type CodeB = Extract<EBlock, { t: 'code' }>;

export const LANGS = ['python', 'typescript', 'javascript', 'tsx', 'json', 'yaml', 'bash', 'shell', 'sql', 'java', 'go', 'rust', 'c', 'cpp', 'csharp', 'kotlin', 'swift', 'php', 'ruby', 'html', 'css', 'markdown', 'xml', 'toml', 'ini', 'dockerfile', 'diff', 'setup', 'bars'];

/** 设计稿 C10：代码块，含可搜索的语言选择器、复制、Tab 缩进 */
export function CodeBlock({ b, ctx }: { b: CodeB; ctx: BlockCtx }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [copied, setCopied] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const setLang = (lang: string) => {
    ctx.update(b.id, { lang });
    setOpen(false);
    setQ('');
  };

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !boxRef.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const needle = q.trim().toLowerCase();
  const options = LANGS.filter((l) => l.includes(needle));
  const custom = needle && !LANGS.includes(needle) && /^[\w+#.-]+$/.test(needle) ? needle : null;

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    if (e.key === 'Tab') {
      e.preventDefault();
      const { selectionStart: s, selectionEnd: end } = el;
      const text = `${el.value.slice(0, s)}    ${el.value.slice(end)}`;
      ctx.update(b.id, { text });
      requestAnimationFrame(() => el.setSelectionRange(s + 4, s + 4));
    } else if (e.key === 'Backspace' && !el.value) {
      e.preventDefault();
      ctx.replace(b.id, { t: 'p', text: '' }, 0);
    } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      ctx.insertAfter(b.id, { t: 'p', text: '' }, 0);
    }
  };

  const copy = () => {
    void navigator.clipboard?.writeText(b.text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const lines = Math.max(1, b.text.split('\n').length);
  return (
    <div className="overflow-visible rounded-[10px] border border-line bg-[#f7f7f5]">
      <div className="flex items-center justify-between border-b border-divider px-3 py-1.5">
        <div ref={boxRef} className="relative">
          <button type="button" onClick={() => setOpen((v) => !v)} aria-haspopup="listbox" aria-expanded={open} className="flex items-center gap-1 rounded-[5px] px-1.5 py-0.5 font-mono text-[11.5px] text-text2 hover:bg-white">
            {b.lang || '纯文本'}
            <ChevronDown aria-hidden className="size-3" />
          </button>
          {open && (
            <div className="absolute top-full left-0 z-30 mt-1 w-[200px] rounded-[10px] border border-line bg-white p-1 shadow-dialog">
              <label className="flex items-center gap-1.5 border-b border-divider px-2 pb-1.5">
                <Search aria-hidden className="size-3 text-muted" />
                <input
                  autoFocus
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      setLang(custom ?? options[0] ?? b.lang);
                    } else if (e.key === 'Escape') setOpen(false);
                  }}
                  placeholder="搜索语言"
                  aria-label="搜索语言"
                  className="min-w-0 flex-1 py-1 text-[12px] outline-none"
                />
              </label>
              <ul role="listbox" aria-label="代码语言" className="max-h-[200px] overflow-y-auto pt-1">
                {[...(custom ? [custom] : []), ...options, ''].map((l) => (
                  <li key={l || 'plain'}>
                    <button type="button" role="option" aria-selected={b.lang === l} onClick={() => setLang(l)} className={cn('flex w-full items-center justify-between rounded-[6px] px-2 py-1 text-left font-mono text-[12px] text-text2 hover:bg-soft', b.lang === l && 'text-ink')}>
                      {l || '纯文本'}
                      {b.lang === l && <Check aria-hidden className="size-3" />}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <button type="button" onClick={copy} className="flex items-center gap-1 text-[11px] text-muted hover:text-ink">
          {copied ? <Check aria-hidden className="size-3" /> : <Copy aria-hidden className="size-3" />}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <div className="flex gap-3 px-3 py-2.5 font-mono text-[12.5px] leading-[1.7]">
        <pre aria-hidden className="shrink-0 text-right text-muted/70 select-none">
          {Array.from({ length: lines }, (_, i) => i + 1).join('\n')}
        </pre>
        <AutoTextarea {...focusAttr(b.id)} value={b.text} spellCheck={false} aria-label="代码" placeholder="// 在这里输入代码，⌘↵ 跳出代码块" onChange={(e) => ctx.update(b.id, { text: e.target.value })} onKeyDown={onKeyDown} className="overflow-x-auto whitespace-pre text-ink" />
      </div>
    </div>
  );
}
