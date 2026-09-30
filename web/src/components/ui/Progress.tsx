import { cn } from '@/lib/cn';

/** 3px 细进度条 */
export function Progress({ value, color = '#1d1d1b', className, label }: { value: number; color?: string; className?: string; label?: string }) {
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      className={cn('h-[3px] overflow-hidden rounded-[2px] bg-divider', className)}
    >
      <div className="h-full rounded-[2px] transition-[width] duration-300" style={{ width: `${Math.min(100, Math.max(0, value))}%`, backgroundColor: color }} />
    </div>
  );
}
