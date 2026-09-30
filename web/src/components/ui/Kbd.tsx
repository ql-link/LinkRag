import { cn } from '@/lib/cn';

/** 快捷键键帽：浅灰底 + 细边框，Inter 10px */
export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <kbd className={cn('inline-flex shrink-0 items-center rounded-[5px] border border-line bg-soft px-1.5 py-0.5 font-num text-[10px] leading-none font-medium text-muted', className)}>
      {children}
    </kbd>
  );
}
