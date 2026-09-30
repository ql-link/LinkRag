import { cn } from '@/lib/cn';

import { levelTone } from './logic';

const TONE_CLS = {
  red: 'bg-red/10 text-red',
  amber: 'bg-amber/10 text-amber',
  blue: 'bg-blue/10 text-blue',
  green: 'bg-green/10 text-green',
  gray: 'bg-muted/10 text-muted',
} as const;

/** 级别徽标（设计稿 Level 52×18）：等宽字体、10% 底色 */
export function LevelBadge({ level, className }: { level: string | null; className?: string }) {
  return (
    <span className={cn('inline-flex h-[18px] w-[52px] items-center justify-center rounded-[4px] font-mono text-[10px] font-semibold tracking-wide', TONE_CLS[levelTone(level)], className)}>
      {level ?? '—'}
    </span>
  );
}
