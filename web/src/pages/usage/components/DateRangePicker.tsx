import { Calendar, ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/cn';
import {
  addDays,
  DATA_START,
  detectPreset,
  formatRange,
  monthEnd,
  monthStart,
  parseCompactDate,
  presetLabel,
  presetRange,
  PRESETS,
  TODAY,
  type DateRange,
  type Preset,
} from '@/services/usage';

interface Props {
  value: DateRange;
  onChange: (r: DateRange) => void;
}

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];
const shiftMonth = (iso: string, n: number) => {
  const [y, m] = iso.split('-').map(Number);
  const d = new Date(Date.UTC(y, m - 1 + n, 1));
  return d.toISOString().slice(0, 10);
};

/** E2 统计周期：快捷周期 + 双月日历；也可直接输入 8 位日期（20260901-20260915），输入完整后自动应用 */
export function DateRangePicker({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', onDown, true);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown, true);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const apply = (r: DateRange) => {
    onChange(r);
    setOpen(false);
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`统计周期：${formatRange(value)}`}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex h-8 items-center gap-[7px] rounded-[7px] border bg-white pr-3 pl-[11px] font-num text-[11.5px] font-medium text-text2',
          open ? 'border-ink' : 'border-line hover:bg-soft',
        )}
      >
        <Calendar aria-hidden className="size-3" />
        {formatRange(value)}
      </button>
      {open && <Popover value={value} onApply={apply} />}
    </div>
  );
}

function Popover({ value, onApply }: { value: DateRange; onApply: (r: DateRange) => void }) {
  const [preset, setPreset] = useState<Preset>(() => detectPreset(value));
  // 选择中的起点；为空表示下一次点击选择起点
  const [anchor, setAnchor] = useState<string | undefined>();
  const [hover, setHover] = useState<string | undefined>();
  // 右侧月份，默认展示结束日期所在月
  const [right, setRight] = useState(() => monthStart(value.to));
  const [typed, setTyped] = useState('');
  const [typedError, setTypedError] = useState(false);

  const pickPreset = (p: Preset) => {
    setPreset(p);
    if (p === 'custom') {
      setAnchor(undefined);
      return;
    }
    onApply(presetRange(p));
  };

  const clickDay = (iso: string) => {
    setPreset('custom');
    if (!anchor) return setAnchor(iso);
    onApply(iso < anchor ? { from: iso, to: anchor } : { from: anchor, to: iso });
  };

  /** 支持 20260901-20260915、20260901 20260915 或单个日期 */
  const onType = (s: string) => {
    setTyped(s);
    setTypedError(false);
    const digits = s.replace(/\D/g, '');
    if (digits.length !== 8 && digits.length !== 16) return;
    const a = parseCompactDate(digits.slice(0, 8));
    const b = digits.length === 16 ? parseCompactDate(digits.slice(8)) : a;
    if (!a || !b || a > TODAY || b > TODAY) return setTypedError(true);
    onApply(a <= b ? { from: a, to: b } : { from: b, to: a });
  };

  // 进行中的选择：anchor 到 hover；否则显示当前值
  const selFrom = anchor ? (hover && hover < anchor ? hover : anchor) : value.from;
  const selTo = anchor ? (hover && hover > anchor ? hover : anchor) : value.to;

  return (
    <div role="dialog" aria-label="选择统计周期" className="absolute top-full right-0 z-40 mt-1.5 flex gap-4 rounded-[14px] border border-line bg-white pt-2.5 pr-[18px] pb-4 pl-2 shadow-pop">
      <div role="listbox" aria-label="快捷周期" className="flex w-24 flex-col gap-0.5 pt-1">
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            role="option"
            aria-selected={preset === p}
            onClick={() => pickPreset(p)}
            className={cn('rounded-[7px] px-2.5 py-[7px] text-left text-[12px]', preset === p ? 'bg-soft font-medium text-ink' : 'text-text2 hover:bg-soft/60')}
          >
            {presetLabel[p]}
          </button>
        ))}
      </div>
      <div aria-hidden className="w-px self-stretch bg-divider" />
      <div className="flex flex-col gap-3">
        <div className="flex gap-4">
          {[shiftMonth(right, -1), right].map((m, i) => (
            <Month
              key={m}
              month={m}
              from={selFrom}
              to={selTo}
              onPick={clickDay}
              onHover={setHover}
              prev={i === 0 ? () => setRight((r) => shiftMonth(r, -1)) : undefined}
              next={i === 1 && monthEnd(right) < TODAY ? () => setRight((r) => shiftMonth(r, 1)) : undefined}
            />
          ))}
        </div>
        <label className="flex items-center gap-2 text-[11px] text-muted">
          <span className="shrink-0">输入日期</span>
          <input
            value={typed}
            onChange={(e) => onType(e.target.value)}
            inputMode="numeric"
            placeholder="20260901-20260915"
            aria-invalid={typedError}
            aria-describedby={typedError ? 'range-typed-error' : undefined}
            className={cn(
              'h-7 min-w-0 flex-1 rounded-[6px] border bg-white px-2 font-num text-[11.5px] text-ink placeholder:text-faint focus:border-ink',
              typedError ? 'border-red' : 'border-line',
            )}
          />
          {typedError ? (
            <span id="range-typed-error" role="alert" className="text-red">
              日期无效
            </span>
          ) : (
            anchor && <span>再选一个日期作为结束</span>
          )}
        </label>
      </div>
    </div>
  );
}

function Month({
  month,
  from,
  to,
  onPick,
  onHover,
  prev,
  next,
}: {
  month: string;
  from: string;
  to: string;
  onPick: (iso: string) => void;
  onHover: (iso?: string) => void;
  prev?: () => void;
  next?: () => void;
}) {
  const [y, m] = month.split('-').map(Number);
  const lead = (new Date(Date.UTC(y, m - 1, 1)).getUTCDay() + 6) % 7;
  const last = Number(monthEnd(month).slice(8));
  const cells: (string | null)[] = [...Array(lead).fill(null), ...Array.from({ length: last }, (_, i) => addDays(month, i))];
  while (cells.length % 7) cells.push(null);

  return (
    <div className="flex w-[210px] flex-col gap-1.5 pt-1.5" onMouseLeave={() => onHover(undefined)}>
      <div className="flex h-[21px] items-center">
        <span className="flex-1 text-[12.5px] font-medium text-ink">
          {y} 年 {m} 月
        </span>
        {prev && (
          <button type="button" aria-label="上个月" onClick={prev} className="rounded p-0.5 text-muted hover:bg-soft hover:text-ink">
            <ChevronLeft className="size-3.5" />
          </button>
        )}
        {next && (
          <button type="button" aria-label="下个月" onClick={next} className="rounded p-0.5 text-muted hover:bg-soft hover:text-ink">
            <ChevronRight className="size-3.5" />
          </button>
        )}
      </div>
      <div role="grid" aria-label={`${y} 年 ${m} 月`} className="mt-1 grid grid-cols-7">
        {WEEKDAYS.map((w) => (
          <span key={w} role="columnheader" className="pb-1.5 text-center text-[10.5px] text-muted">
            {w}
          </span>
        ))}
        {cells.map((iso, i) => {
          if (!iso) return <span key={`e${i}`} className="h-7" />;
          const disabled = iso > TODAY;
          const edge = iso === from || iso === to;
          const inRange = iso > from && iso < to;
          return (
            <button
              key={iso}
              type="button"
              role="gridcell"
              disabled={disabled}
              aria-selected={edge || inRange}
              aria-label={iso}
              onClick={() => onPick(iso)}
              onMouseEnter={() => onHover(iso)}
              className={cn(
                'h-7 font-num text-[11.5px] font-medium',
                edge ? 'rounded-[7px] bg-ink text-white' : inRange ? 'bg-soft text-text2' : 'rounded-[7px] text-text2 hover:bg-soft',
                iso === TODAY && !edge && 'text-ink underline decoration-dotted underline-offset-4',
                iso < DATA_START && !edge && !inRange && 'text-faint',
                disabled && 'cursor-not-allowed text-faint hover:bg-transparent',
              )}
            >
              {Number(iso.slice(8))}
            </button>
          );
        })}
      </div>
    </div>
  );
}
