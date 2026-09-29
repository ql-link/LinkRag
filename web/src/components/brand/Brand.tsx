import markDark from '@/assets/brand/logo-mark-dark.png';
import mark from '@/assets/brand/logo-mark.png';

import { cn } from '@/lib/cn';

import { Wordmark } from './Wordmark';

interface BrandProps {
  /** logo 尺寸：侧栏 32 / 登录页 34 */
  size?: 32 | 34;
  dark?: boolean;
  className?: string;
}

/** LinkRag 品牌标识：logo 图形 + 字标（字标按设计稿比例 74×20 缩放） */
export function Brand({ size = 32, dark, className }: BrandProps) {
  const wordHeight = size === 34 ? 29.6 : 19.7;
  return (
    <div className={cn('flex items-center', size === 34 ? 'gap-[9px]' : 'gap-1.5', className)}>
      <img src={dark ? markDark : mark} alt="" width={size} height={size} className="shrink-0 object-contain" />
      <Wordmark role="img" aria-label="LinkRag" height={wordHeight} width={wordHeight * 3.745} className={dark ? 'text-[#f2f2f2]' : 'text-ink'} />
    </div>
  );
}
