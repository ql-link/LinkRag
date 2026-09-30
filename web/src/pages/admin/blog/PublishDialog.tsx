import { AlertCircle, Check, X } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';

import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Spinner } from '@/components/ui/Loading';

import { blogApi, type BlogAsset, type BlogPost } from './api';
import { referencedUrls } from './editorOps';

type Level = 'ok' | 'warn' | 'fail';

interface Props {
  open: boolean;
  onClose: () => void;
  post: BlogPost | null;
  title: string;
  summary: string;
  markdown: string;
  dirty: boolean;
  onConfirm: () => Promise<void>;
}

const ICON: Record<Level, ReactNode> = {
  ok: <Check aria-hidden className="size-3 text-green" />,
  warn: <AlertCircle aria-hidden className="size-3 text-amber" />,
  fail: <X aria-hidden className="size-3 text-red" />,
};
const BG: Record<Level, string> = { ok: 'bg-green/10', warn: 'bg-amber/10', fail: 'bg-red/10' };

/** 设计稿 C6 发布确认：逐项检查，正文为空时禁止发布；有未保存修改时先保存再发布 */
export function PublishDialog({ open, onClose, post, title, summary, markdown, dirty, onConfirm }: Props) {
  const [images, setImages] = useState<BlogAsset[] | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || !post) return;
    setImages(null);
    blogApi
      .assets(post.id, 'CONTENT_IMAGE')
      .then(setImages)
      .catch(() => setImages([]));
  }, [open, post]);

  const refs = referencedUrls(markdown);
  const unused = (images ?? []).filter((a) => !refs.has(a.publicUrl)).length;
  const hasBody = !!markdown.replace(/^---\n[\s\S]*?\n---\n?/, '').trim();
  const rows: { level: Level; label: string; value: string }[] = [
    { level: title.trim() ? 'ok' : 'warn', label: '标题', value: title.trim() || '未填写，将显示为「未命名文章」' },
    { level: 'ok', label: 'Slug', value: post ? `/blogs/${post.slug}` : '保存后生成' },
    { level: summary.trim() ? 'ok' : 'warn', label: '摘要', value: summary.trim() ? `${summary.trim().length} 字` : '未填写，官网将截取正文首段' },
    { level: post?.coverAssetId ? 'ok' : 'warn', label: '封面图', value: post?.coverAssetId ? '已设置' : '未设置，官网将使用分类默认封面' },
    { level: hasBody ? 'ok' : 'fail', label: '正文', value: hasBody ? (dirty ? '有未保存的修改，将先保存' : '已保存') : '正文为空，无法发布' },
    { level: images === null ? 'ok' : unused ? 'warn' : 'ok', label: '正文插图', value: images === null ? '检查中…' : unused ? `${unused} 张未在正文中使用` : images.length ? '均已引用' : '无插图' },
  ];

  const confirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={busy ? () => undefined : onClose}
      width={500}
      title="发布文章"
      description="发布后将出现在官网 /blogs 列表"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button onClick={() => void confirm()} disabled={busy || !hasBody} data-autofocus>
            {busy ? '正在发布…' : '确认发布'}
          </Button>
        </>
      }
    >
      <ul className="flex flex-col divide-y divide-divider">
        {rows.map((r) => (
          <li key={r.label} className="flex items-center gap-3 py-2.5">
            <span className={`flex size-5 shrink-0 items-center justify-center rounded-full ${BG[r.label === '正文插图' && images === null ? 'ok' : r.level]}`}>{r.label === '正文插图' && images === null ? <Spinner className="size-3" /> : ICON[r.level]}</span>
            <span className="w-16 shrink-0 text-[12.5px] text-ink">{r.label}</span>
            <span className={`min-w-0 flex-1 truncate text-right text-[12px] ${r.level === 'fail' ? 'text-red' : 'text-muted'}`}>{r.value}</span>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
