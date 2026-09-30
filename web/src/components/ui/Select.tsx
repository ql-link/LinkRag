import { ChevronDown, Lock } from 'lucide-react';

import { ModelBadge } from '@/components/ModelBadge';
import { cn } from '@/lib/cn';

interface ModelSelectProps {
  id?: string;
  value: string;
  options: string[];
  onChange?: (v: string) => void;
  locked?: boolean;
  size?: 'md' | 'sm';
  className?: string;
  ariaLabel?: string;
}

/** 带模型徽标的下拉选择；locked 时为只读展示 */
export function ModelSelect({ id, value, options, onChange, locked, size = 'md', className, ariaLabel }: ModelSelectProps) {
  const h = size === 'md' ? 'h-10 rounded-[9px] px-3 gap-[9px]' : 'h-[34px] rounded-lg px-2.5 gap-2';
  const text = size === 'md' ? 'text-[13px]' : 'text-[12px] font-medium';
  if (locked) {
    return (
      <div id={id} aria-label={ariaLabel} className={cn('flex items-center border border-line bg-soft text-text2', h, className)}>
        <ModelBadge model={value} size={18} />
        <span className={cn('flex-1 truncate', text)}>{value}</span>
        <Lock aria-hidden className="size-3 text-muted" />
      </div>
    );
  }
  return (
    <div className={cn('relative flex items-center border border-line bg-white focus-within:border-ink', h, className)}>
      <ModelBadge model={value} size={size === 'md' ? 20 : 18} />
      <span className={cn('flex-1 truncate text-ink', text)}>{value}</span>
      <ChevronDown aria-hidden className={size === 'md' ? 'size-[13px] text-muted' : 'size-3 text-muted'} />
      <select
        id={id}
        aria-label={ariaLabel}
        value={value}
        onChange={(e) => onChange?.(e.target.value)}
        className="absolute inset-0 cursor-pointer opacity-0"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </div>
  );
}
