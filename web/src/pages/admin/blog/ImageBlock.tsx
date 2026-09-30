import { Copy, ImageIcon, Link2, RefreshCw, Trash2, Upload } from 'lucide-react';
import { useRef, useState } from 'react';

import { Spinner } from '@/components/ui/Loading';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';

import { focusAttr, type BlockCtx } from './blockCtx';
import type { EBlock } from './blocks';

type ImgB = Extract<EBlock, { t: 'img' }>;

const tool = 'flex items-center gap-1 rounded-[6px] px-2 py-1 text-[11.5px] text-text2 hover:bg-soft hover:text-ink';

/** 设计稿 C9：图片块。空块 = 拖入 / 选择 / 粘贴链接；上传中显示进度；已插入时悬停出现工具栏 */
export function ImageBlock({ b, ctx }: { b: ImgB; ctx: BlockCtx }) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [url, setUrl] = useState('');
  const [broken, setBroken] = useState(false);

  const pick = (f: File | undefined) => f && ctx.uploadImage(b.id, f);
  const input = <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/gif,image/webp" hidden onChange={(e) => (pick(e.target.files?.[0]), (e.target.value = ''))} />;
  const dropProps = {
    onDragOver: (e: React.DragEvent) => {
      if (![...e.dataTransfer.types].includes('Files')) return;
      e.preventDefault();
      e.stopPropagation();
      setOver(true);
    },
    onDragLeave: () => setOver(false),
    onDrop: (e: React.DragEvent) => {
      const f = e.dataTransfer.files[0];
      if (!f) return;
      e.preventDefault();
      e.stopPropagation();
      setOver(false);
      pick(f);
    },
  };

  if (b.uploading)
    return (
      <figure className="relative overflow-hidden rounded-[10px] border border-line bg-soft" aria-busy>
        {b.src && <img src={b.src} alt="" className="max-h-[360px] w-full object-contain opacity-50" />}
        <div className={cn('flex items-center justify-center gap-2 text-[12px] text-text2', b.src ? 'absolute inset-0' : 'py-12')}>
          <span className="flex items-center gap-2 rounded-full bg-white/90 px-3 py-1.5 shadow-seg">
            <Spinner className="size-3.5" />
            正在上传 {b.alt || '图片'}…
          </span>
        </div>
      </figure>
    );

  if (!b.src)
    return (
      <div {...dropProps} className={cn('flex flex-col items-center gap-3 rounded-[10px] border border-dashed px-6 py-8 text-center transition-colors', over ? 'border-ink bg-soft' : 'border-line bg-[#fbfbfa]')}>
        {input}
        <ImageIcon aria-hidden className="size-5 text-muted" />
        <p className="text-[12.5px] text-text2">{over ? '松开以插入' : '拖入图片、粘贴截图，或'}</p>
        <div className="flex items-center gap-2">
          <button type="button" {...focusAttr(b.id)} onClick={() => fileRef.current?.click()} className="flex items-center gap-1.5 rounded-[7px] border border-line bg-white px-3 py-1.5 text-[12px] text-text2 hover:bg-soft">
            <Upload aria-hidden className="size-3.5" />
            选择图片
          </button>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (/^(https?:\/\/|\/)\S+$/.test(url.trim())) ctx.update(b.id, { src: url.trim() });
              else toast('请输入以 http(s):// 或 / 开头的图片地址', { tone: 'error' });
            }}
            className="flex items-center gap-1.5 rounded-[7px] border border-line bg-white px-2 py-1"
          >
            <Link2 aria-hidden className="size-3.5 text-muted" />
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="或粘贴图片链接后回车" aria-label="图片链接" className="w-[200px] text-[12px] outline-none" />
          </form>
          <button type="button" onClick={() => ctx.remove(b.id)} aria-label="移除图片块" className="rounded-[6px] p-1.5 text-muted hover:bg-soft hover:text-red">
            <Trash2 className="size-3.5" />
          </button>
        </div>
        <p className="text-[11px] text-muted">JPG / PNG / GIF / WebP，不超过 10 MB</p>
      </div>
    );

  return (
    <figure {...dropProps} className="group flex flex-col gap-1.5">
      {input}
      <div className={cn('relative overflow-hidden rounded-[10px] border bg-soft', over ? 'border-ink' : 'border-line')}>
        {broken ? (
          <div className="flex flex-col items-center gap-1 py-10 text-[12px] text-muted">
            <ImageIcon aria-hidden className="size-5" />
            图片无法加载：<span className="max-w-full truncate px-6 font-mono text-[11px]">{b.src}</span>
          </div>
        ) : (
          <img src={b.src} alt={b.alt} onError={() => setBroken(true)} className="mx-auto max-h-[480px] w-full object-contain" />
        )}
        {over && <div className="absolute inset-0 flex items-center justify-center bg-white/70 text-[13px] font-medium text-ink">松开以替换</div>}
        <div className="absolute top-2 right-2 flex items-center gap-0.5 rounded-[8px] border border-line bg-white/95 p-1 shadow-toast opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
          <button type="button" className={tool} onClick={() => fileRef.current?.click()}>
            <RefreshCw aria-hidden className="size-3" />
            替换
          </button>
          <button type="button" className={tool} onClick={() => void navigator.clipboard?.writeText(b.src).then(() => toast('已复制图片链接', { tone: 'success' }))}>
            <Copy aria-hidden className="size-3" />
            复制链接
          </button>
          <button type="button" className={tool} aria-label="删除图片" onClick={() => ctx.remove(b.id)}>
            <Trash2 aria-hidden className="size-3" />
          </button>
        </div>
      </div>
      <input
        {...focusAttr(b.id)}
        value={b.alt}
        onChange={(e) => ctx.update(b.id, { alt: e.target.value })}
        onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), ctx.insertAfter(b.id, { t: 'p', text: '' }, 0))}
        placeholder="添加图注（同时作为替代文字）"
        aria-label="图注"
        className="bg-transparent text-center text-[12px] text-muted outline-none"
      />
    </figure>
  );
}
