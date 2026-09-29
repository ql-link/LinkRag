import { cn } from '@/lib/cn';

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  count?: number;
  countTone?: 'red';
}

interface SegmentedProps<T extends string> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: 'sm' | 'lg';
  block?: boolean;
  ariaLabel?: string;
}

export function Segmented<T extends string>({ options, value, onChange, size = 'sm', block, ariaLabel }: SegmentedProps<T>) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn('flex gap-0.5 bg-soft p-[3px]', size === 'lg' ? 'rounded-[9px]' : 'rounded-lg', block && 'w-full')}
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              'flex items-center justify-center gap-1.5 leading-none whitespace-nowrap transition-colors',
              size === 'lg' ? 'flex-1 rounded-[7px] py-[7px] text-[12.5px]' : 'rounded-md px-[11px] py-[5px] text-[12px]',
              active ? 'bg-white font-medium text-ink shadow-seg' : 'text-text2 hover:text-ink',
            )}
          >
            {opt.label}
            {opt.count !== undefined && (
              <span className={cn('font-num text-[10.5px] font-medium', opt.countTone === 'red' && opt.count > 0 ? 'text-red' : 'text-muted')}>
                {opt.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
