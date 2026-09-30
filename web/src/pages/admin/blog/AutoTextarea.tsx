import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, type TextareaHTMLAttributes } from 'react';

import { cn } from '@/lib/cn';

/** 随内容自动增高的无边框文本域：块编辑器里所有可输入文本都用它，便于处理选区与快捷键 */
export const AutoTextarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement> & { value: string }>(function AutoTextarea({ className, value, ...rest }, ref) {
  const inner = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => inner.current!);
  useLayoutEffect(() => {
    const el = inner.current;
    if (!el) return;
    el.style.height = '0px';
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);
  return <textarea ref={inner} rows={1} value={value} className={cn('block w-full resize-none overflow-hidden bg-transparent outline-none placeholder:text-muted/70', className)} {...rest} />;
});

/** 把选区用前后缀包起来（已包裹则去掉），返回新文本与新选区 */
export function wrapSelection(text: string, start: number, end: number, before: string, after = before) {
  const sel = text.slice(start, end);
  if (text.slice(start - before.length, start) === before && text.slice(end, end + after.length) === after)
    return { text: text.slice(0, start - before.length) + sel + text.slice(end + after.length), start: start - before.length, end: end - before.length };
  return { text: text.slice(0, start) + before + sel + after + text.slice(end), start: start + before.length, end: end + before.length };
}
