import { ImageIcon, Upload } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Loading';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';

import { actionBtn, StateFeedback } from '../StateFeedback';
import { blogApi, checkImage, errMsg, fileSize, type BlogAsset, type BlogPost } from './api';
import { useImageSize } from './useImageMeta';

interface Props {
  open: boolean;
  onClose: () => void;
  /** 新文章需要先建草稿才能上传 */
  ensurePost: () => Promise<BlogPost>;
  post: BlogPost | null;
  onCoverChange: (coverAssetId: number | null, url: string | null) => void;
}

/** 设计稿 C4 封面图弹窗：上传后后端自动设为封面；移除 = 清空 coverAssetId */
export function CoverDialog({ open, onClose, ensurePost, post, onCoverChange }: Props) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [cover, setCover] = useState<BlogAsset | null>(null);
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle');
  const [busy, setBusy] = useState<'upload' | 'remove' | null>(null);
  const [over, setOver] = useState(false);
  const size = useImageSize(cover?.publicUrl);

  const load = useCallback(() => {
    if (!post?.coverAssetId) return setCover(null);
    setState('loading');
    blogApi
      .assets(post.id, 'COVER')
      .then((l) => {
        setCover(l.find((a) => a.id === post.coverAssetId) ?? null);
        setState('idle');
      })
      .catch(() => setState('error'));
  }, [post?.id, post?.coverAssetId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    const bad = checkImage(file);
    if (bad) return toast(bad, { tone: 'error' });
    setBusy('upload');
    try {
      const p = await ensurePost();
      const asset = await blogApi.upload(p.id, 'COVER', file);
      setCover(asset);
      onCoverChange(asset.id, asset.publicUrl);
      toast('封面已更新', { tone: 'success' });
    } catch (e) {
      toast(errMsg(e, '封面上传失败'), { tone: 'error' });
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    if (!post) return;
    setBusy('remove');
    try {
      await blogApi.update(post.id, { coverAssetId: null });
      if (cover) await blogApi.removeAsset(post.id, cover.id).catch(() => undefined);
      setCover(null);
      onCoverChange(null, null);
      toast('已移除封面');
    } catch (e) {
      toast(errMsg(e, '移除失败'), { tone: 'error' });
    } finally {
      setBusy(null);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      width={560}
      title="文章封面"
      description="推荐尺寸 1200 × 630 · JPEG / PNG / WebP · 不超过 10 MB"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button onClick={onClose} disabled={!!busy}>
            完成
          </Button>
        </>
      }
    >
      <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/gif,image/webp" hidden onChange={(e) => (void upload(e.target.files?.[0]), (e.target.value = ''))} />
      {state === 'loading' ? (
        <StateFeedback kind="loading" title="正在加载封面" />
      ) : state === 'error' ? (
        <StateFeedback kind="error" title="封面加载失败" action={<button type="button" className={actionBtn} onClick={load}>重新加载</button>} />
      ) : (
        <div className="flex flex-col gap-3">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => (e.preventDefault(), setOver(true))}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(false);
              void upload(e.dataTransfer.files[0]);
            }}
            aria-label={cover ? '更换封面' : '上传封面'}
            className={cn('relative flex aspect-[1200/630] w-full items-center justify-center overflow-hidden rounded-[12px] border bg-soft', over ? 'border-ink' : cover ? 'border-line' : 'border-dashed border-line')}
          >
            {cover ? (
              <img src={cover.publicUrl} alt="当前封面" className="size-full object-cover" />
            ) : (
              <span className="flex flex-col items-center gap-2 text-[12.5px] text-muted">
                <ImageIcon aria-hidden className="size-6" />
                {over ? '松开以上传' : '点击或拖入图片上传封面'}
              </span>
            )}
            {busy === 'upload' && (
              <span className="absolute inset-0 flex items-center justify-center bg-white/70 text-[12px] text-text2">
                <Spinner className="mr-2 size-4" />
                正在上传…
              </span>
            )}
          </button>
          {cover && (
            <div className="flex items-center gap-2">
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-[12.5px] text-ink">{cover.originalFilename}</span>
                <span className="font-num text-[11px] text-muted">
                  {size ? `${size.w} × ${size.h} · ` : ''}
                  {fileSize(cover.fileSize)}
                </span>
              </div>
              <Button variant="secondary" icon={<Upload aria-hidden className="size-3.5" />} disabled={!!busy} onClick={() => fileRef.current?.click()}>
                重新上传
              </Button>
              <button type="button" disabled={!!busy} onClick={() => void remove()} className="rounded-[7px] px-3 py-2 text-[12px] text-red hover:bg-red/10 disabled:opacity-50">
                {busy === 'remove' ? '正在移除…' : '移除'}
              </button>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}
