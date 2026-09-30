import { useRef, useState, type KeyboardEvent } from 'react';

/** 设计稿 C11 源码模式：带行号的 Markdown 文本域，状态栏显示光标行列 */
export function SourceEditor({ value, onChange, onCursor }: { value: string; onChange: (v: string) => void; onCursor: (line: number, col: number) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const gutter = useRef<HTMLPreElement>(null);
  const [lines, setLines] = useState(() => value.split('\n').length);

  const report = () => {
    const el = ref.current;
    if (!el) return;
    const before = el.value.slice(0, el.selectionStart).split('\n');
    onCursor(before.length, before[before.length - 1].length + 1);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Tab') return;
    e.preventDefault();
    const el = e.currentTarget;
    const s = el.selectionStart;
    onChange(`${el.value.slice(0, s)}  ${el.value.slice(el.selectionEnd)}`);
    requestAnimationFrame(() => el.setSelectionRange(s + 2, s + 2));
  };

  return (
    <div className="flex min-h-[560px] overflow-hidden rounded-[12px] border border-line bg-white font-mono text-[12.5px] leading-[1.75]">
      <pre ref={gutter} aria-hidden className="shrink-0 overflow-hidden border-r border-divider bg-[#fafaf8] px-3 py-4 text-right text-muted/70 select-none">
        {Array.from({ length: Math.max(lines, value.split('\n').length) }, (_, i) => i + 1).join('\n')}
      </pre>
      <textarea
        ref={ref}
        value={value}
        spellCheck={false}
        aria-label="Markdown 源码"
        onChange={(e) => {
          onChange(e.target.value);
          setLines(e.target.value.split('\n').length);
        }}
        onKeyDown={onKeyDown}
        onSelect={report}
        onClick={report}
        onScroll={(e) => gutter.current && (gutter.current.scrollTop = e.currentTarget.scrollTop)}
        placeholder={'---\ncategory: 技术\ntags: [示例]\n---\n\n## 第一节 {#s1}\n\n正文…'}
        className="min-w-0 flex-1 resize-none bg-transparent px-4 py-4 whitespace-pre text-ink outline-none"
      />
    </div>
  );
}
