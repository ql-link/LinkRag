import { Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { useToast } from '@/contexts/ToastContext';

import { blogApi, errMsg, type BlogPost } from './api';

/** 设计稿 C2 删除确认 */
export function DeletePostDialog({ post, onClose, onDeleted }: { post: BlogPost | null; onClose: () => void; onDeleted: (id: number) => void }) {
  const toast = useToast();
  const [images, setImages] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setImages(null);
    if (!post) return;
    let alive = true;
    blogApi
      .assets(post.id, 'CONTENT_IMAGE')
      .then((l) => alive && setImages(l.length))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [post]);

  const confirm = async () => {
    if (!post) return;
    setBusy(true);
    try {
      await blogApi.remove(post.id);
      toast(`已删除「${post.title}」`, { tone: 'success' });
      onDeleted(post.id);
    } catch (e) {
      toast(errMsg(e, '删除失败'), { tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={!!post}
      onClose={busy ? () => undefined : onClose}
      width={440}
      title="删除文章"
      description="此操作不可撤销"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button variant="danger" onClick={confirm} disabled={busy} data-autofocus>
            {busy ? '正在删除…' : '删除文章'}
          </Button>
        </>
      }
    >
      <div className="flex gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-red/10">
          <Trash2 aria-hidden className="size-4 text-red" />
        </span>
        <div className="flex min-w-0 flex-col gap-1.5">
          <p className="text-[13px] font-medium text-ink">确定要彻底删除「{post?.title}」吗？</p>
          <p className="text-[12px] leading-5 text-muted">
            正文、封面{images ? `与 ${images} 张正文插图` : '与正文插图'}将一并删除{post?.status === 'PUBLISHED' ? '，已分享的链接会失效' : ''}。
          </p>
        </div>
      </div>
    </Dialog>
  );
}
