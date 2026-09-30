import { ChevronDown, ChevronUp, Check } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

/** 数字输入：带单位与上下步进；modified 为琥珀边框，invalid 为红色边框 */
export function NumberInput({
  value,
  onChange,
  step = 1,
  min,
  max,
  unit,
  modified,
  invalid,
  label,
  decimals = 0,
}: {
  value: number;
  onChange: (v: number) => void;
  step?: number;
  min?: number;
  max?: number;
  unit?: string;
  modified?: boolean;
  invalid?: boolean;
  label: string;
  decimals?: number;
}) {
  const clamp = (v: number) => Math.min(max ?? Infinity, Math.max(min ?? -Infinity, v));
  const bump = (d: number) => onChange(Number(clamp(value + d).toFixed(decimals)));
  return (
    <div
      className={cn(
        'flex h-[34px] w-[132px] items-center gap-1.5 rounded-lg border bg-white pr-1.5 pl-2.5',
        invalid ? 'border-red' : modified ? 'border-amber' : 'border-line focus-within:border-ink',
      )}
    >
      <input
        type="number"
        inputMode="decimal"
        aria-label={label}
        aria-invalid={invalid || undefined}
        value={Number.isFinite(value) ? value : ''}
        step={step}
        onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))}
        className="w-full min-w-0 [appearance:textfield] bg-transparent font-num text-[12.5px] font-medium text-ink outline-none [&::-webkit-inner-spin-button]:appearance-none"
      />
      {unit && <span className="text-[10.5px] text-muted">{unit}</span>}
      <span className="flex flex-col rounded bg-soft px-1 py-px text-muted">
        <button type="button" tabIndex={-1} aria-label={`增加${label}`} onClick={() => bump(step)} className="hover:text-ink">
          <ChevronUp className="size-2" strokeWidth={3} />
        </button>
        <button type="button" tabIndex={-1} aria-label={`减少${label}`} onClick={() => bump(-step)} className="hover:text-ink">
          <ChevronDown className="size-2" strokeWidth={3} />
        </button>
      </span>
    </div>
  );
}

/** 滑块 + 数值 */
export function Slider({ value, onChange, min, max, label }: { value: number; onChange: (v: number) => void; min: number; max: number; label: string }) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div className="flex items-center gap-2.5">
      <input
        type="range"
        aria-label={label}
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ background: `linear-gradient(to right, #1d1d1b ${pct}%, #ececea ${pct}%)` }}
        className="h-1 w-[120px] cursor-pointer appearance-none rounded-full [&::-moz-range-thumb]:size-3.5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border [&::-moz-range-thumb]:border-line [&::-moz-range-thumb]:bg-white [&::-webkit-slider-thumb]:size-3.5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-line [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:shadow-[0_1px_3px_rgba(0,0,0,0.15)]"
      />
      <span className="w-8 font-num text-[12px] font-medium text-ink">{value}</span>
    </div>
  );
}

/** 多选分段：选中项白底 + 勾 */
export function MultiToggle<K extends string>({ options, value, onChange, label }: { options: { key: K; label: string }[]; value: Record<K, boolean>; onChange: (v: Record<K, boolean>) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="flex gap-0.5 rounded-lg bg-soft p-[3px]">
      {options.map((o) => {
        const on = value[o.key];
        return (
          <button
            key={o.key}
            type="button"
            aria-pressed={on}
            onClick={() => onChange({ ...value, [o.key]: !on })}
            className={cn('flex items-center gap-[5px] rounded-md px-[11px] py-[5px] text-[12px] leading-none', on ? 'bg-white font-medium text-ink shadow-seg' : 'text-text2 hover:text-ink')}
          >
            {on && <Check aria-hidden className="size-2.5" strokeWidth={3} />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** 配置分组卡片 */
export function ConfigCard({ id, icon, title, en, description, chip, children }: { id: string; icon: ReactNode; title: string; en: string; description: string; chip?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-6 rounded-[14px] border border-line bg-white shadow-[0_4px_16px_0_rgba(0,0,0,0.03)]">
      <header className="flex items-center gap-3 px-[18px] py-3.5">
        <span className="flex size-[30px] shrink-0 items-center justify-center rounded-lg bg-soft text-text2 [&>svg]:size-3.5">{icon}</span>
        <div className="flex min-w-0 flex-col gap-[3px]">
          <div className="flex items-baseline gap-[7px]">
            <h2 id={`${id}-title`} className="text-[14px] font-medium text-ink">
              {title}
            </h2>
            <span className="text-[10.5px] font-medium text-faint">{en}</span>
          </div>
          <p className="text-[11.5px] text-muted">{description}</p>
        </div>
        <span className="flex-1" />
        {chip}
      </header>
      {children}
    </section>
  );
}

/** 配置项行：左侧说明，右侧控件 */
export function ParamRow({ label, help, modified, note, noteTone, children }: { label: string; help?: string; modified?: boolean; note?: string; noteTone?: 'amber' | 'red'; children: ReactNode }) {
  return (
    <div className="flex items-center gap-4 border-t border-divider px-[18px] py-3">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-ink">
          {label}
          {modified && <span aria-label="已修改" className="size-1.5 rounded-full bg-amber" />}
        </div>
        {help && <p className="max-w-[480px] text-[11px] leading-[17px] text-muted">{help}</p>}
        {note && (
          <p role={noteTone === 'red' ? 'alert' : undefined} className={cn('text-[11px]', noteTone === 'red' ? 'text-red' : 'text-amber')}>
            {note}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2.5">{children}</div>
    </div>
  );
}
