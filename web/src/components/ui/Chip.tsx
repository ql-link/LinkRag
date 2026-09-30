import { cn } from '@/lib/cn';

export type Tone = 'green' | 'amber' | 'red' | 'blue' | 'gray';

const tones: Record<Tone, string> = {
  green: 'bg-green/10 text-green',
  amber: 'bg-amber/10 text-amber',
  red: 'bg-red/10 text-red',
  blue: 'bg-blue/10 text-blue',
  gray: 'bg-muted/10 text-muted',
};

/** 状态标签：10% 底色 + 5px 圆点 + 10.5px 文字 */
export function Chip({ tone, children, dot = true, className }: { tone: Tone; children: React.ReactNode; dot?: boolean; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-[5px] rounded-[5px] px-[7px] py-[3px] text-[10.5px] leading-none font-medium whitespace-nowrap',
        tones[tone],
        className,
      )}
    >
      {dot && <span aria-hidden className="size-[5px] rounded-full bg-current" />}
      {children}
    </span>
  );
}
