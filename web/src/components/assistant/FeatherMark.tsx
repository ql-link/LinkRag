import feather from '@/assets/assistant/feather.png';
import { cn } from '@/lib/cn';

const INK = 'M 3 34 C 10 33 16 31 22 27 C 27 24 30 19 28 15 C 27 11 22 12 20 17 C 17 23 20 29 26 30 C 32 31 35 26 40 28 C 44 31 48 28 53 25';

/**
 * 助手头像（复刻 LinkCV 助手）：静态为一支羽毛笔；writing 时羽毛沿墨迹路径书写，表示 AI 正在思考。
 * 动效定义在 index.css（.feather-writing），开启「减少动态效果」时保持静止。
 */
export function FeatherMark({ writing, size = 28, className }: { writing?: boolean; size?: number; className?: string }) {
  if (!writing) return <img src={feather} alt="" aria-hidden style={{ width: size, height: size }} className={cn('shrink-0 object-contain', className)} />;
  return (
    <span aria-hidden className={cn('feather-writing relative block h-11 w-14 shrink-0', className)}>
      <svg className="feather-ink absolute inset-0 size-full overflow-visible" viewBox="0 0 56 44" focusable="false">
        <path pathLength={1} d={INK} fill="none" stroke="var(--color-blue)" strokeWidth={1.35} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      </svg>
      <img src={feather} alt="" className="feather-pen z-[1] h-8 w-7 object-contain" />
    </span>
  );
}
