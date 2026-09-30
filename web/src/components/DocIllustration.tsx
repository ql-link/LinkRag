import { cn } from '@/lib/cn';
import type { FileType } from '@/types';

import { TypeTag } from './FileBadge';

/** 单张文档卡片：白底 + 深色标题条 + 灰色正文线 */
export function DocCard({ w = 68, h = 80, lines = 5, className, style }: { w?: number; h?: number; lines?: number; className?: string; style?: React.CSSProperties }) {
  const small = w < 60;
  return (
    <div
      style={{ width: w, height: h, ...style }}
      className={cn('absolute overflow-hidden rounded-[5px] border border-line bg-white shadow-doc', className)}
    >
      <div className={cn('absolute rounded-[2px] bg-ink', small ? 'top-2 left-[7px] h-1 w-6' : 'top-2.5 left-2 h-[5px] w-[30px]')} />
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          style={{ top: (small ? 18 : 22) + i * (small ? 8 : 9), width: i === lines - 1 && !small ? 28 : small ? 40 : 48 }}
          className={cn('absolute h-[3px] rounded-[1px] bg-divider', small ? 'left-[7px]' : 'left-2')}
        />
      ))}
    </div>
  );
}

/** 知识库卡片封面：三张（或两张）倾斜文档 + 类型标签，262×110 */
export function DatasetCover({ type, className }: { type: FileType; className?: string }) {
  const three = type === 'PDF';
  return (
    <div aria-hidden className={cn('relative h-[110px] w-full overflow-hidden rounded-[11px] bg-soft', className)}>
      <div className="absolute top-0 left-1/2 h-full w-[262px] -translate-x-1/2">
        {three ? (
          <>
            <DocCard w={56} h={66} lines={4} className="-rotate-6" style={{ left: 62, top: 25 }} />
            <DocCard w={56} h={66} lines={4} style={{ left: 103, top: 22 }} />
            <DocCard w={56} h={66} lines={4} className="rotate-6" style={{ left: 143, top: 31 }} />
          </>
        ) : (
          <>
            <DocCard w={56} h={66} lines={4} className="-rotate-3" style={{ left: 83, top: 23 }} />
            <DocCard w={56} h={66} lines={4} className="rotate-3" style={{ left: 123, top: 26 }} />
          </>
        )}
        <TypeTag type={type} style={{ left: 172, top: 70 }} />
      </div>
    </div>
  );
}

/** 上传区 / 登录页使用的大号三文档插画 */
export function DocTrio({ className }: { className?: string }) {
  return (
    <div aria-hidden className={cn('relative h-24 w-[220px]', className)}>
      <DocCard className="-rotate-6" style={{ left: 18, top: 10 }} />
      <TypeTag type="PDF" style={{ left: 72, top: 57 }} />
      <DocCard style={{ left: 76, top: 6 }} />
      <TypeTag type="MD" style={{ left: 130, top: 46 }} />
      <DocCard className="rotate-6" style={{ left: 132, top: 16 }} />
      <TypeTag type="DOCX" style={{ left: 184, top: 58 }} />
    </div>
  );
}
