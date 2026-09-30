import { ArrowLeft, ExternalLink, ImageIcon, MoreHorizontal, Trash2, Upload } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { Menu } from '@/components/ui/Menu';
import { Segmented } from '@/components/ui/Segmented';

import { relTime } from '../ui';
import type { BlogPost } from './api';

export type Mode = 'wysiwyg' | 'source';

interface Props {
  post: BlogPost | null;
  isNew: boolean;
  dirty: boolean;
  saving: boolean;
  savedAt: Date | null;
  mode: Mode;
  onMode: (m: Mode) => void;
  onBack: () => void;
  onImport: () => void;
  onLibrary: () => void;
  onSave: () => void;
  onPublish: () => void;
  onUnpublish: () => void;
  onDelete: () => void;
  statusBusy: boolean;
}

const hm = (d: Date) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

/** 设计稿 C3 / C6 顶栏：返回 · 面包屑 · 保存状态 · 模式切换 · 导入 · 插图库 · 更多 · 保存 · 发布 / 下架 */
export function EditorTopbar(p: Props) {
  const published = p.post?.status === 'PUBLISHED';
  const status = p.saving ? '正在保存…' : p.dirty ? '有未保存的修改' : published && p.post?.publishedAt ? `发布于 ${relTime(p.post.publishedAt)}` : p.savedAt ? `已保存 · ${hm(p.savedAt)}` : p.post ? `更新于 ${relTime(p.post.updatedAt)}` : '尚未保存';
  return (
    <div className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-divider bg-white/95 px-5 backdrop-blur">
      <button type="button" onClick={p.onBack} aria-label="返回文章列表" className="flex size-8 items-center justify-center rounded-[7px] border border-line text-text2 hover:bg-soft">
        <ArrowLeft className="size-3.5" />
      </button>
      <div className="flex min-w-0 flex-col">
        <p className="text-[11px] text-muted">
          <Link to="/admin/blog" className="hover:text-ink">
            文章管理
          </Link>
          <span className="mx-1">/</span>
          <span className="text-text2">{p.isNew ? '写文章' : '编辑文章'}</span>
        </p>
        <p className={`text-[11px] ${p.dirty ? 'text-amber' : 'text-muted'}`} aria-live="polite">
          {status}
        </p>
      </div>
      {p.post && <Chip tone={published ? 'green' : 'gray'}>{published ? '已发布' : '草稿'}</Chip>}
      <div className="ml-auto flex items-center gap-2">
        <Segmented<Mode> ariaLabel="编辑模式" value={p.mode} onChange={p.onMode} options={[{ value: 'wysiwyg', label: '所见即所得' }, { value: 'source', label: '源码' }]} />
        <Button variant="secondary" icon={<Upload aria-hidden className="size-3.5" />} onClick={p.onImport}>
          导入 Markdown
        </Button>
        <Button variant="secondary" icon={<ImageIcon aria-hidden className="size-3.5" />} onClick={p.onLibrary}>
          插图库
        </Button>
        <Menu
          width={160}
          trigger={({ toggle }) => (
            <button type="button" onClick={toggle} aria-label="更多操作" className="flex size-8 items-center justify-center rounded-[7px] border border-line bg-white text-text2 hover:bg-soft">
              <MoreHorizontal className="size-3.5" />
            </button>
          )}
          items={[
            ...(published && p.post ? [{ key: 'view', label: '在官网查看', icon: <ExternalLink className="size-3.5" />, onSelect: () => window.open(`/blog/${encodeURIComponent(p.post!.slug)}`, '_blank', 'noopener') }] : []),
            ...(p.post ? [{ key: 'del', label: '删除文章', danger: true, divider: published, icon: <Trash2 className="size-3.5" />, onSelect: p.onDelete }] : []),
          ]}
        />
        <Button variant="secondary" onClick={p.onSave} disabled={p.saving || (!p.dirty && !!p.post)}>
          {p.saving ? '保存中…' : '保存'}
        </Button>
        {published ? (
          <Button onClick={p.onUnpublish} disabled={p.statusBusy}>
            {p.statusBusy ? '处理中…' : '下架文章'}
          </Button>
        ) : (
          <Button onClick={p.onPublish} disabled={p.statusBusy || p.saving}>
            发布文章
          </Button>
        )}
      </div>
    </div>
  );
}
