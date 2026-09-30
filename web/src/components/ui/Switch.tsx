import { cn } from '@/lib/cn';

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  tone?: 'ink' | 'green';
  disabled?: boolean;
}

/** 开关：30×18 轨道，14px 圆钮 */
export function Switch({ checked, onChange, label, tone = 'ink', disabled }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-[18px] w-[30px] shrink-0 rounded-full transition-colors disabled:opacity-50',
        checked ? (tone === 'green' ? 'bg-green' : 'bg-ink') : 'bg-dash',
      )}
    >
      <span className={cn('absolute top-0.5 size-3.5 rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.2)] transition-[left]', checked ? 'left-[14px]' : 'left-0.5')} />
    </button>
  );
}
