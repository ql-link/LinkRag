import { Check, Code, Copy, Plus, Trash2, Upload } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';

import { actionBtn, StateFeedback } from '../StateFeedback';
import { blogApi, checkImage, errMsg, type BlogAsset, type BlogPost } from './api';

interface Props {
  open: boolean;
  onClose: () => void;
  post: BlogPost | null;
  ensurePost: () => Promise<BlogPost>;
  /** 当前正文（含未保存修改），用于标注「未使用」 */
  markdown: string;
  onInsert: (asset: BlogAsset) => void;
}

const refOf = (a: BlogAsset) => a.markdownText || `![${a.originalFilename.replace(/\.\w+$/, '')}](${a.publicUrl})`;

/** 设计稿 C5 插图库：本文的 CONTENT_IMAGE，复制引用 / 插入正文 / 删除（正文仍引用时后端返回 400） */
export function IllustrationLibrary({ open, onClose, post, ensurePost, markdown, onInsert }: Props) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<BlogAsset[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  const [uploading, setUploading] = useState(0);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(() => {
    if (!post) return setItems([]);
    setError(null);
    blogApi
      .assets(post.id, 'CONTENT_IMAGE')
      .then(setItems)
      .catch((e) => setError(errMsg(e, '加载失败')));
  }, [post?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const upload = async (files: File[]) => {
    const ok = files.filter((f) => {
      const bad = checkImage(f);
      if (bad) toast(`${f.name}：${bad}`, { tone: 'error' });
      return !bad;
    });
    if (!ok.length) return;
    setUploading((n) => n + ok.length);
    try {
      const p = await ensurePost();
      for (const f of ok) {
        try {
          const a = await blogApi.upload(p.id, 'CONTENT_IMAGE', f);
          setItems((l) => [a, ...(l ?? [])]);
        } catch (e) {
          toast(`${f.name} 上传失败：${errMsg(e)}`, { tone: 'error' });
        } finally {
          setUploading((n) => n - 1);
        }
      }
    } catch (e) {
      setUploading(0);
      toast(errMsg(e, '上传失败'), { tone: 'error' });
    }
  };

  const copy = (a: BlogAsset) =>
    void navigator.clipboard?.writeText(refOf(a)).then(() => {
      setCopied(a.id);
      setTimeout(() => setCopied((c) => (c === a.id ? null : c)), 1600);
    });

  const remove = async (a: BlogAsset) => {
    if (!post) return;
    if (markdown.includes(a.publicUrl)) return toast('正文仍在引用这张图片，请先从正文中移除', { tone: 'error' });
    setBusyId(a.id);
    try {
      await blogApi.removeAsset(post.id, a.id);
      setItems((l) => l && l.filter((x) => x.id !== a.id));
    } catch (e) {
      toast(errMsg(e, '删除失败'), { tone: 'error' });
    } finally {
      setBusyId(null);
    }
  };

  const unused = (items ?? []).filter((a) => !markdown.includes(a.publicUrl)).length;
  const preview = items?.find((a) => a.id === copied);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      width={640}
      title="文章内插图"
      description={items ? `共 ${items.length} 张${unused ? ` · ${unused} 张未在正文中使用` : ''} · 点击复制 Markdown 引用后粘贴至正文` : '管理本文上传的正文插图'}
      footer={<Button variant="secondary" onClick={onClose}>关闭</Button>}
    >
      <input ref={fileRef} type="file" multiple accept="image/jpeg,image/png,image/gif,image/webp" hidden onChange={(e) => (void upload([...(e.target.files ?? [])]), (e.target.value = ''))} />
      <div className="mb-3 flex justify-end">
        <Button variant="secondary" icon={<Upload aria-hidden className="size-3.5" />} onClick={() => fileRef.current?.click()} disabled={uploading > 0}>
          {uploading > 0 ? `正在上传 ${uploading} 张…` : '上传新图片'}
        </Button>
      </div>
      {error ? (
        <StateFeedback kind="error" title="插图加载失败" desc={error} action={<button type="button" className={actionBtn} onClick={load}>重新加载</button>} />
      ) : !items ? (
        <StateFeedback kind="loading" title="正在加载插图" />
      ) : items.length === 0 && !uploading ? (
        <StateFeedback kind="empty" title="还没有插图" desc="上传图片，或直接把图片拖入 / 粘贴到正文中。" />
      ) : (
        <ul className="grid grid-cols-4 gap-3">
          {items.map((a) => {
            const used = markdown.includes(a.publicUrl);
            return (
              <li key={a.id} className="group flex flex-col gap-1.5">
                <div className={cn('relative aspect-[4/3] overflow-hidden rounded-[10px] border bg-soft', copied === a.id ? 'border-ink' : 'border-line')}>
                  <img src={a.publicUrl} alt={a.originalFilename} className="size-full object-cover" loading="lazy" />
                  {!used && <span className="absolute top-1.5 left-1.5 rounded-[5px] bg-white/90 px-1.5 py-0.5 text-[10px] text-amber">未使用</span>}
                  <div className="absolute inset-x-1.5 bottom-1.5 flex gap-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                    <button type="button" onClick={() => copy(a)} className="flex flex-1 items-center justify-center gap-1 rounded-[6px] border border-line bg-white/95 py-1 text-[11px] text-ink hover:bg-soft">
                      {copied === a.id ? <Check aria-hidden className="size-3" /> : <Copy aria-hidden className="size-3" />}
                      {copied === a.id ? '已复制' : '复制引用'}
                    </button>
                    <button type="button" onClick={() => onInsert(a)} aria-label={`插入 ${a.originalFilename}`} title="插入正文" className="rounded-[6px] border border-line bg-white/95 px-1.5 text-text2 hover:bg-soft">
                      <Plus className="size-3" />
                    </button>
                    <button type="button" disabled={busyId === a.id} onClick={() => void remove(a)} aria-label={`删除 ${a.originalFilename}`} title={used ? '正文仍在引用' : '删除'} className="rounded-[6px] border border-line bg-white/95 px-1.5 text-text2 hover:text-red disabled:opacity-50">
                      <Trash2 className="size-3" />
                    </button>
                  </div>
                </div>
                <span className="truncate text-[11.5px] text-text2">{a.originalFilename}</span>
              </li>
            );
          })}
        </ul>
      )}
      {preview && (
        <p className="mt-3 flex items-center gap-2 rounded-[8px] bg-soft px-3 py-2 font-mono text-[11px] text-text2">
          <Code aria-hidden className="size-3.5 shrink-0 text-muted" />
          <span className="truncate">{refOf(preview)}</span>
        </p>
      )}
    </Dialog>
  );
}
