import { useState } from 'react';

import { cn } from '@/lib/cn';

/**
 * 厂商标识：先渲染字母方块（品牌色底 + Inter Bold 白字，字号约为边长的 0.4），
 * logo（后端 sys_provider.icon_url / 系统 logo）加载成功后再覆盖显示；
 * 加载中或失败时始终保留字母方块，不会出现空白。
 */
export function ProviderMark({ letter, color, iconUrl, size = 28, className }: { letter: string; color: string; iconUrl?: string; size?: number; className?: string }) {
  const [loaded, setLoaded] = useState<string>();
  const [failed, setFailed] = useState<string>();
  const radius = size >= 36 ? 10 : size >= 28 ? 8 : 5;
  const showImg = !!iconUrl && failed !== iconUrl;
  const ready = showImg && loaded === iconUrl;
  return (
    <span aria-hidden style={{ width: size, height: size, borderRadius: radius }} className={cn('relative flex shrink-0 overflow-hidden', className)}>
      <span
        style={{ backgroundColor: color, fontSize: size * 0.4 }}
        className={cn('flex size-full items-center justify-center font-num leading-none font-bold text-white transition-opacity duration-200', ready && 'opacity-0')}
      >
        {letter}
      </span>
      {showImg && (
        <img
          src={iconUrl}
          alt=""
          draggable={false}
          onLoad={() => setLoaded(iconUrl)}
          onError={() => setFailed(iconUrl)}
          className={cn('absolute inset-0 size-full object-contain transition-opacity duration-200', ready ? 'opacity-100' : 'opacity-0')}
        />
      )}
    </span>
  );
}
