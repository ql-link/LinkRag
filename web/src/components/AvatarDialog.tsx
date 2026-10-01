import { useEffect, useRef, useState, type PointerEvent } from 'react';

import closeIcon from '@/assets/account/close.svg';
import cropGuide from '@/assets/account/crop-guide.svg';
import uploadIcon from '@/assets/account/upload.svg';
import { UserAvatar } from '@/components/UserAvatar';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/contexts/ToastContext';
import { clampCrop, cropImageStyle, cropSize, exportAvatar, loadAvatar, type CropImage, type CropPosition } from '@/lib/avatarCrop';
import { cn } from '@/lib/cn';

export function AvatarDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return open ? <AvatarEditor onClose={onClose} /> : null;
}

function AvatarEditor({ onClose }: { onClose: () => void }) {
  const { user, uploadAvatar } = useAuth();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const selection = useRef(0);
  const drag = useRef<{ x: number; y: number; position: CropPosition; scale: number } | null>(null);
  const [image, setImage] = useState<CropImage | null>(null);
  const [position, setPosition] = useState<CropPosition>({ x: 0, y: 0, zoom: 1 });
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [over, setOver] = useState(false);

  useEffect(() => () => { selection.current += 1; }, []);
  useEffect(() => () => { if (image) URL.revokeObjectURL(image.url); }, [image]);

  const choose = async (file?: File) => {
    if (!file || busy) return;
    const id = ++selection.current;
    setLoading(true);
    setError('');
    try {
      const next = await loadAvatar(file);
      if (id !== selection.current) { URL.revokeObjectURL(next.url); return; }
      setImage(next);
      setPosition({ x: next.width / 2, y: next.height / 2, zoom: 1 });
    } catch (e) {
      if (id === selection.current) setError(e instanceof Error ? e.message : '图片读取失败。');
    } finally {
      if (id === selection.current) setLoading(false);
    }
  };
  const close = () => { if (!busy) onClose(); };
  const zoom = (value: number) => { if (image) setPosition((current) => clampCrop(image, { ...current, zoom: value })); };
  const save = async () => {
    if (!image || loading || busy) return;
    setBusy(true);
    setError('');
    try {
      await uploadAvatar(await exportAvatar(image, position));
      toast('头像已更新', { tone: 'success' });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : '头像上传失败，请重试。');
    } finally {
      setBusy(false);
    }
  };
  const startDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (!image || busy || loading) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, position, scale: event.currentTarget.getBoundingClientRect().width * 0.9 / cropSize(image, position.zoom) };
  };
  if (!user) return null;
  const canvasImageStyle = image ? Object.fromEntries(Object.entries(cropImageStyle(image, position, 100, 0.9)).map(([key, value]) => [key, `${value}%`])) : undefined;

  return (
    <Dialog
      open onClose={close} title={image ? '调整头像' : '修改头像'}
      description={image ? '拖动图片调整位置，通过缩放让主体完整显示。' : '选择一张清晰的图片，让团队更容易认识你。'}
      width={image ? 680 : 560}
      className="rounded-2xl p-7 [&_h2]:font-sans [&_h2]:text-[22px] [&_h2]:font-medium"
      closeIcon={<img src={closeIcon} alt="" className="size-5" />}
      footer={<><Button variant="secondary" disabled={busy} onClick={close}>取消</Button><Button disabled={!image || busy || loading} onClick={() => void save()}>{busy ? '保存中…' : '保存头像'}</Button></>}
    >
      <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" aria-label="选择头像图片" className="hidden" onChange={(event) => { void choose(event.target.files?.[0]); event.target.value = ''; }} />
      {image ? (
        <div className="flex flex-wrap gap-6">
          <div className="min-w-0 flex-1 basis-[352px] rounded-xl bg-account-soft p-4">
            <div
              role="group" aria-label="头像裁剪区域" tabIndex={0}
              className="relative mx-auto aspect-square w-full max-w-[320px] touch-none overflow-hidden rounded-lg bg-active cursor-grab active:cursor-grabbing"
              onPointerDown={startDrag}
              onPointerMove={(event) => { if (drag.current && !busy && !loading) setPosition(clampCrop(image, { ...drag.current.position, x: drag.current.position.x - (event.clientX - drag.current.x) / drag.current.scale, y: drag.current.position.y - (event.clientY - drag.current.y) / drag.current.scale })); }}
              onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}
              onKeyDown={(event) => {
                if (busy || loading || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
                event.preventDefault();
                const step = cropSize(image, position.zoom) / 50;
                setPosition(clampCrop(image, { ...position, x: position.x + (event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0), y: position.y + (event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0) }));
              }}
            >
              <img src={image.url} alt="待裁剪的头像" draggable={false} className="pointer-events-none absolute max-w-none select-none" style={canvasImageStyle} />
              <img src={cropGuide} alt="" draggable={false} className="pointer-events-none absolute inset-0 size-full" />
            </div>
            <div className="mt-5 flex items-center gap-3">
              <button type="button" aria-label="缩小头像" disabled={busy || loading || position.zoom <= 1} onClick={() => zoom(position.zoom - 0.1)} className="size-7 rounded text-lg hover:bg-active disabled:opacity-40">−</button>
              <input type="range" aria-label="头像缩放" min={1} max={3} step={0.01} value={position.zoom} disabled={busy || loading} onChange={(event) => zoom(Number(event.target.value))} className="min-w-0 flex-1 accent-ink" />
              <button type="button" aria-label="放大头像" disabled={busy || loading || position.zoom >= 3} onClick={() => zoom(position.zoom + 0.1)} className="size-7 rounded text-lg hover:bg-active disabled:opacity-40">+</button>
              <output className="w-10 text-right font-num text-xs text-text2">{Math.round(position.zoom * 100)}%</output>
            </div>
            <p className="mt-3 text-center text-xs text-account-muted">拖动图片或使用方向键调整位置</p>
          </div>
          <div className="flex min-w-0 flex-1 basis-[248px] flex-col items-center rounded-xl border border-account-line p-5 text-center">
            <h3 className="text-sm font-medium">头像预览</h3>
            <div className="relative mt-5 size-28 overflow-hidden rounded-full bg-active">
              <img src={image.url} alt="新头像预览" className="absolute max-w-none" style={cropImageStyle(image, position, 112)} />
            </div>
            <p className="mt-4 text-xs leading-5 text-account-muted">头像将在个人资料与侧栏中显示</p>
            <p className="mt-auto w-full truncate pt-6 text-xs text-text2" title={image.name}>{image.name}</p>
            <Button variant="secondary" className="mt-3 w-full" disabled={busy || loading} onClick={() => input.current?.click()}>重新选择</Button>
          </div>
        </div>
      ) : (
        <div>
          <div className="flex items-center gap-4 rounded-xl bg-account-soft p-4">
            <UserAvatar user={user} className="size-16 text-2xl" />
            <div><h3 className="text-sm font-medium">当前头像</h3><p className="mt-2 text-xs text-account-muted">{user.avatarUrl ? '上传新图片可替换当前头像。' : '暂未上传图片，当前使用名字首字母。'}</p></div>
          </div>
          <div
            className={cn('mt-5 flex cursor-pointer flex-col items-center rounded-xl border border-dashed border-account-line p-6 text-center', over && 'border-ink bg-account-soft')}
            onClick={() => { if (!loading) input.current?.click(); }}
            onDragOver={(event) => { event.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(event) => { event.preventDefault(); setOver(false); void choose(event.dataTransfer.files[0]); }}
          >
            <img src={uploadIcon} alt="" className="size-7" />
            <p className="mt-4 text-sm font-medium">点击上传或拖拽图片到此处</p>
            <p className="mt-2 text-xs text-account-muted">JPG、PNG 或 WebP，文件不超过 5 MB</p>
            <Button variant="secondary" className="mt-5" disabled={loading}>选择图片</Button>
          </div>
          <p className="mt-4 text-xs leading-5 text-account-muted">建议使用正方形图片，尺寸不低于 256 × 256 像素。</p>
        </div>
      )}
      {loading && <p role="status" className="mt-4 text-xs text-text2">正在读取图片…</p>}
      {error && <p role="alert" className="mt-4 text-sm text-account-danger">{error}</p>}
    </Dialog>
  );
}
