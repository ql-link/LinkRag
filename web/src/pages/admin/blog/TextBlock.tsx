/**
 * 文本块的两种形态（Typora 式实时渲染）：
 * - RenderedText：未聚焦时按 Markdown 渲染（标题 / 段落 / 列表 / 引用 / 提示块 + 行内格式）；
 *   点击时把点击位置换算为源码偏移，切换为源码编辑并把光标放到对应位置。
 * - MdBlock：聚焦时显示该块的 Markdown 源码。文本域叠在一层同字体的着色镜像上，
 *   语法标记（#、-、>、**、` 等）置灰，块级样式随首行语法实时变化（输入 `# ` 立即变为一级标题）。
 *   失焦后由编辑器重新解析为普通块。
 */
import { AlertCircle } from 'lucide-react';
import { Fragment, useLayoutEffect, useRef, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';

import { cn } from '@/lib/cn';
import { highlightInline, Inline, rawOffsetOf } from '@/lib/inlineMarkdown';

import { focusAttr, hotkeyWrap, pendingCaret, reportSelection, type BlockCtx } from './blockCtx';
import { wrapSelection } from './AutoTextarea';
import type { EBlock } from './blocks';
import { mdEnter, setHeadingLevel } from './editorOps';

type TextB = Extract<EBlock, { t: 'p' | 'h' | 'list' | 'quote' | 'callout' }>;
type MdB = Extract<EBlock, { t: 'md' }>;

const PROSE = 'text-[15px] leading-[1.8] text-text2';
const STYLE: Record<string, string> = {
  p: PROSE,
  h1: 'font-serif text-[26px] leading-snug font-semibold text-ink',
  h2: 'font-serif text-[22px] leading-snug font-semibold text-ink',
  h3: 'text-[18px] leading-snug font-semibold text-ink',
  h4: 'text-[16px] leading-snug font-semibold text-ink',
  h5: 'text-[15px] leading-snug font-semibold text-ink',
  h6: 'text-[14px] leading-snug font-semibold text-text2',
  quote: `${PROSE} italic`,
  callout: 'text-[14px] leading-[1.7] text-text2',
};
const PAD: Record<string, string> = { h1: 'pt-5', h2: 'pt-4', h3: 'pt-2', h4: 'pt-1.5' };

/** 块级外框：引用左边线、提示块底色；源码态与渲染态共用，切换时不跳动 */
function Frame({ kind, children }: { kind: string; children: ReactNode }) {
  if (kind === 'quote') return <div className="border-l-[3px] border-line py-0.5 pl-4">{children}</div>;
  if (kind === 'callout')
    return (
      <div className="flex gap-2.5 rounded-[10px] border border-amber/25 bg-amber/10 px-3.5 py-3">
        <AlertCircle aria-hidden className="mt-1 size-3.5 shrink-0 text-amber" />
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    );
  return <div className={PAD[kind]}>{children}</div>;
}

const kindOf = (b: TextB) => (b.t === 'h' ? `h${b.level}` : b.t === 'list' ? 'p' : b.t);

/** 源码首行 → 块样式 */
function mdKind(src: string) {
  const h = /^(#{1,6})(?:[ \t]|$)/.exec(src);
  if (h) return `h${h[1].length}`;
  if (/^>[ \t]?\*\*/.test(src)) return 'callout';
  if (src.startsWith('>')) return 'quote';
  return 'p';
}

/* ---------------- 渲染态 ---------------- */

/** 一段可点击定位的行内文本：data-src 为其在块源码中的起始偏移 */
function Line({ src, start, className }: { src: string; start: number; className?: string }) {
  return (
    <span data-src={start} data-inline={src} className={className}>
      <Inline text={src} />
    </span>
  );
}

function caretFromPoint(x: number, y: number): { node: Node; offset: number } | null {
  const d = document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  };
  if (d.caretPositionFromPoint) {
    const p = d.caretPositionFromPoint(x, y);
    return p && { node: p.offsetNode, offset: p.offset };
  }
  const r = d.caretRangeFromPoint?.(x, y);
  return r ? { node: r.startContainer, offset: r.startOffset } : null;
}

/** 点击位置 → 块源码偏移；落在文字以外时返回 'end' */
function sourceOffsetAt(e: MouseEvent): number | 'end' {
  const hit = caretFromPoint(e.clientX, e.clientY);
  const el = (hit?.node instanceof Element ? hit.node : hit?.node.parentElement)?.closest<HTMLElement>('[data-src]');
  if (!hit || !el || !e.currentTarget.contains(el)) return 'end';
  const range = document.createRange();
  range.setStart(el, 0);
  range.setEnd(hit.node, hit.offset);
  return Number(el.dataset.src) + rawOffsetOf(el.dataset.inline ?? '', range.toString().length);
}

/** 各行在 serializeBlock 输出中的起始偏移（与 blocks.ts 的序列化规则逐字对应） */
function body(b: TextB): ReactNode {
  const lines = (text: string, first: number, prefix = 0, cls?: string) => {
    let at = first;
    return text.split('\n').map((l, i) => {
      const start = at + prefix;
      at += prefix + l.length + 1;
      return (
        <Fragment key={i}>
          {i > 0 && <br />}
          <Line src={l} start={start} className={cls} />
        </Fragment>
      );
    });
  };
  switch (b.t) {
    case 'p':
      return lines(b.text.trim(), 0);
    case 'h':
      return <Line src={b.text.trim()} start={b.level + 1} />;
    case 'quote':
      return lines(b.text.trim(), 0, 2);
    case 'callout': {
      const label = b.label.trim() || '提示';
      const text = b.text.trim();
      const [head, ...rest] = text.split('\n');
      const headStart = 4 + label.length + 3;
      return (
        <>
          <Line src={label} start={4} className="mr-2 text-[13px] font-semibold text-[#8a5a14]" />
          <Line src={head} start={headStart} />
          {rest.length > 0 && (
            <>
              <br />
              {lines(rest.join('\n'), headStart + head.length + 1, 2)}
            </>
          )}
        </>
      );
    }
    case 'list': {
      let at = 0;
      return (
        <ol className="flex flex-col gap-1" aria-label={b.ordered ? '有序列表' : '无序列表'}>
          {b.items.map((it, n) => {
            const mark = b.ordered ? `${n + 1}. ` : '- ';
            const start = at + mark.length;
            at = start + it.length + 1;
            return (
              <li key={n} className="flex gap-2">
                <span aria-hidden className="w-5 shrink-0 text-right font-num text-muted">
                  {b.ordered ? `${n + 1}.` : '•'}
                </span>
                <Line src={it} start={start} className="min-w-0 flex-1" />
              </li>
            );
          })}
        </ol>
      );
    }
  }
}

export function RenderedText({ b, ctx, first }: { b: TextB; ctx: BlockCtx; first: boolean }) {
  const kind = kindOf(b);
  const empty = b.t === 'list' ? b.items.every((it) => !it.trim()) : !b.text.trim();
  return (
    <Frame kind={kind}>
      <div
        {...focusAttr(b.id)}
        role="textbox"
        tabIndex={0}
        aria-label={`${kind === 'p' ? '段落' : kind.startsWith('h') ? `${kind.slice(1)} 级标题` : kind === 'quote' ? '引用' : '提示块'}，点击编辑`}
        onMouseDown={(e) => {
          // ⌘ / Ctrl + 点击链接：直接打开，不进入编辑
          if (e.button !== 0 || ((e.metaKey || e.ctrlKey) && (e.target as HTMLElement).closest('a'))) return;
          // 阻止默认聚焦 / 选区，由源码文本域接管光标
          e.preventDefault();
          pendingCaret.set(b.id, sourceOffsetAt(e));
          ctx.edit(b.id);
        }}
        onClick={(e) => !(e.metaKey || e.ctrlKey) && e.preventDefault()}
        onFocus={() => ctx.edit(b.id)}
        className={cn(STYLE[kind], 'cursor-text break-words outline-none')}
      >
        {empty ? <span className="text-muted/70">{first ? '从这里开始写正文，输入 / 插入块' : '空白段落'}</span> : body(b)}
      </div>
    </Frame>
  );
}

/* ---------------- 源码态 ---------------- */

const mark = (s: string, k: string) => (
  <span key={k} className="text-faint">
    {s}
  </span>
);

function highlightLine(line: string, k: number): ReactNode[] {
  if (/^```/.test(line) || /^(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) return [mark(line, `${k}`)];
  const m = /^(?:#{1,6}(?=[ \t]|$)[ \t]*|[ \t]*(?:[-*+]|\d+[.)])[ \t]+|>[ \t]?)/.exec(line);
  const pre = m?.[0] ?? '';
  return [pre && mark(pre, `${k}p`), <Fragment key={`${k}i`}>{highlightInline(line.slice(pre.length))}</Fragment>];
}

const PLACEHOLDER: Record<string, string> = { p: '输入 / 唤起命令，或直接输入 Markdown：# 标题、- 列表、> 引用、``` 代码块', quote: '引用内容', callout: '提示内容' };

export function MdBlock({ b, ctx, first }: { b: MdB; ctx: BlockCtx; first: boolean }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const kind = mdKind(b.src);
  const set = (src: string) => ctx.update(b.id, { src });
  const caret = (pos: number) => requestAnimationFrame(() => ref.current?.setSelectionRange(pos, pos));

  // 进入源码态即聚焦，光标位置来自点击 / focusEl
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const want = pendingCaret.get(b.id);
    pendingCaret.delete(b.id);
    const pos = want === undefined || want === 'end' ? el.value.length : Math.min(want, el.value.length);
    el.focus();
    el.setSelectionRange(pos, pos);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const onChange = (el: HTMLTextAreaElement) => {
    const src = el.value;
    if (/^\/\S*$/.test(src)) ctx.slash(el, b.id, src.slice(1));
    else ctx.slash(null, b.id, '');
    set(src);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    const { selectionStart: s, selectionEnd: end, value } = el;
    const wrap = hotkeyWrap(e);
    if (wrap && s !== end) {
      e.preventDefault();
      const next = wrapSelection(value, s, end, ...wrap);
      set(next.text);
      requestAnimationFrame(() => el.setSelectionRange(next.start, next.end));
      return;
    }
    // ⌘⌥1–6 标题级别，⌘⌥0 段落（浏览器占用了 ⌘1–9 切换标签页）
    if ((e.metaKey || e.ctrlKey) && e.altKey && /^Digit[0-6]$/.test(e.code)) {
      e.preventDefault();
      const next = setHeadingLevel(value, Number(e.code.slice(5)));
      set(next);
      caret(next.length - (value.length - s));
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      el.blur();
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      const act = mdEnter(value, s, end);
      switch (act.kind) {
        case 'insert':
          set(act.text);
          caret(act.caret);
          return;
        case 'split':
          set(act.before);
          return ctx.insertAfter(b.id, { t: 'md', src: act.after }, 0);
        case 'exit':
          if (!act.before.trim()) return ctx.replace(b.id, { t: 'md', src: act.after }, 0);
          set(act.before);
          return ctx.insertAfter(b.id, { t: 'md', src: act.after }, 0);
        case 'code':
          return ctx.replace(b.id, { t: 'code', lang: act.lang, text: '' }, 0);
        case 'table':
          return ctx.replace(b.id, { t: 'table', head: act.head, rows: [act.head.map(() => '')] }, 0);
        case 'hr':
          ctx.replace(b.id, { t: 'hr' });
          return ctx.insertAfter(b.id, { t: 'md', src: '' }, 0);
      }
    }
    const atStart = s === 0 && end === 0;
    if (e.key === 'Backspace' && atStart && !first) {
      e.preventDefault();
      ctx.mergeUp(b.id, value);
    } else if (e.key === 'ArrowUp' && !value.slice(0, s).includes('\n') && (atStart || s === end)) {
      if (atStart || s === 0) {
        e.preventDefault();
        ctx.focusNeighbor(b.id, -1);
      }
    } else if (e.key === 'ArrowDown' && s === value.length) {
      e.preventDefault();
      ctx.focusNeighbor(b.id, 1);
    }
  };

  const lines = b.src.split('\n');
  return (
    <Frame kind={kind}>
      <div className={cn(STYLE[kind], 'relative break-words whitespace-pre-wrap')}>
        {/* 着色镜像：决定高度；文本域透明叠放其上，只显示光标与选区 */}
        <div aria-hidden className="pointer-events-none">
          {lines.map((l, i) => (
            <Fragment key={i}>
              {i > 0 && '\n'}
              {highlightLine(l, i)}
            </Fragment>
          ))}
          {'\u200b'}
        </div>
        <textarea
          ref={ref}
          {...focusAttr(b.id)}
          value={b.src}
          rows={1}
          spellCheck={false}
          aria-label="Markdown 源码"
          placeholder={first && !b.src ? '从这里开始写正文，输入 / 插入块' : (PLACEHOLDER[kind] ?? '')}
          onChange={(e) => onChange(e.currentTarget)}
          onKeyDown={onKeyDown}
          onSelect={(e) => reportSelection(ctx, e.currentTarget, set)}
          onBlur={() => {
            ctx.slash(null, b.id, '');
            // 焦点移到格式栏（如链接输入框）时保持源码态
            setTimeout(() => {
              const active = document.activeElement;
              if (active === ref.current || active?.closest('[data-editor-keep]')) return;
              ctx.settle(b.id);
            });
          }}
          className="absolute inset-0 size-full resize-none overflow-hidden bg-transparent break-words whitespace-pre-wrap text-transparent caret-ink outline-none selection:bg-blue/20 placeholder:text-muted/70"
          style={{ font: 'inherit', letterSpacing: 'inherit' }}
        />
      </div>
    </Frame>
  );
}
