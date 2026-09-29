import { cn } from '@/lib/cn';
import type { FileType } from '@/types';

export const typeColor: Record<FileType, string> = {
  PDF: '#d0493f',
  DOCX: '#3f6fd8',
  MD: '#3b9a5b',
  XLSX: '#3b9a5b',
  TXT: '#96968f',
  ZIP: '#d9912b',
};

/** 文件类型方块：30px，类型色 10% 底 + Inter Bold 8.5px */
export function FileBadge({ type, className }: { type: FileType; className?: string }) {
  const color = typeColor[type];
  return (
    <span
      aria-hidden
      style={{ color, backgroundColor: `${color}1a` }}
      className={cn('flex size-[30px] shrink-0 items-center justify-center rounded-[7px] font-num text-[8.5px] font-bold', className)}
    >
      {type}
    </span>
  );
}

/** 实心类型标签：白字，用于插画 */
export function TypeTag({ type, className, style }: { type: FileType; className?: string; style?: React.CSSProperties }) {
  return (
    <span
      style={{ backgroundColor: typeColor[type], ...style }}
      className={cn('absolute rounded px-[5px] py-0.5 font-num text-[9px] leading-none font-bold text-white', className)}
    >
      {type}
    </span>
  );
}
