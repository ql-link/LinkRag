import { ChevronDown, Plus, Upload } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { Button } from '@/components/ui/Button';
import { Menu } from '@/components/ui/Menu';
import { SearchBox } from '@/components/ui/SearchBox';
import { Segmented } from '@/components/ui/Segmented';
import { useToast } from '@/contexts/ToastContext';

import { AdminColumn } from '../AdminLayout';
import { actionBtn, StaleBanner, StateFeedback } from '../StateFeedback';
import { AdminHeader, fmt, Pagination } from '../ui';
import { blogApi, errMsg, type BlogPost } from './api';
import { DeletePostDialog } from './DeletePostDialog';
import { filterPosts, parseStatus, SORT_LABEL, titleFromMarkdown, type SortKey, type StatusFilter } from './listLogic';
import { PostRow } from './PostRow';

const PAGE_SIZE = 6;

/** 设计稿 C1 文章列表 / C2 搜索无结果 · 空态 · 删除确认 */
export default function BlogAdminListPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const status = parseStatus(params.get('status'));
  const [posts, setPosts] = useState<BlogPost[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState('');
  const [sort, setSort] = useState<SortKey>('updated');
  const [page, setPage] = useState(1);
  const [deleting, setDeleting] = useState<BlogPost | null>(null);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const reload = useCallback(() => {
    setLoading(true);
    blogApi
      .listAll()
      .then((l) => {
        setPosts(l);
        setError(null);
      })
      .catch((e) => setError(errMsg(e, '加载失败')))
      .finally(() => setLoading(false));
  }, []);
  useEffect(reload, [reload]);
  useEffect(() => setPage(1), [status, keyword, sort]);

  const counts = useMemo(() => {
    const l = posts ?? [];
    return { ALL: l.length, PUBLISHED: l.filter((p) => p.status === 'PUBLISHED').length, DRAFT: l.filter((p) => p.status === 'DRAFT').length };
  }, [posts]);
  const shown = useMemo(() => filterPosts(posts ?? [], status, keyword, sort), [posts, status, keyword, sort]);
  const current = Math.min(page, Math.max(1, Math.ceil(shown.length / PAGE_SIZE)));
  const pageItems = shown.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  const setStatus = (s: StatusFilter) => {
    const next = new URLSearchParams(params);
    if (s === 'ALL') next.delete('status');
    else next.set('status', s);
    setParams(next, { replace: true });
  };

  const onImport = async (file: File | undefined) => {
    if (!file) return;
    if (!/\.(md|markdown)$/i.test(file.name)) return toast('请选择 .md 或 .markdown 文件', { tone: 'error' });
    setImporting(true);
    try {
      const created = await blogApi.create({ title: titleFromMarkdown(await file.text(), file.name) });
      try {
        await blogApi.importMarkdown(created.id, file);
      } catch (e) {
        toast(`已创建草稿，但导入正文失败：${errMsg(e)}`, { tone: 'error' });
        return navigate(`/admin/blog/${created.id}`);
      }
      toast('已导入为草稿', { tone: 'success' });
      navigate(`/admin/blog/${created.id}`);
    } catch (e) {
      toast(errMsg(e, '导入失败'), { tone: 'error' });
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <AdminColumn>
      <AdminHeader
        eyebrow={`博客管理 · 共 ${posts ? fmt(posts.length) : '—'} 篇`}
        title="文章管理"
        desc="管理官网博客的草稿与已发布内容。"
        actions={
          <>
            <input ref={fileRef} type="file" accept=".md,.markdown,text/markdown" hidden onChange={(e) => void onImport(e.target.files?.[0])} />
            <Button variant="secondary" icon={<Upload aria-hidden className="size-3.5" />} disabled={importing} onClick={() => fileRef.current?.click()}>
              {importing ? '正在导入…' : '导入 Markdown'}
            </Button>
            <Button icon={<Plus aria-hidden className="size-3.5" />} onClick={() => navigate('/admin/blog/new')}>
              写文章
            </Button>
          </>
        }
      />
      <div className="mb-2 flex items-center gap-3">
        <Segmented<StatusFilter>
          ariaLabel="按状态筛选"
          value={status}
          onChange={setStatus}
          options={[
            { value: 'ALL', label: '全部', count: counts.ALL },
            { value: 'PUBLISHED', label: '已发布', count: counts.PUBLISHED },
            { value: 'DRAFT', label: '草稿', count: counts.DRAFT },
          ]}
        />
        <SearchBox value={keyword} onChange={setKeyword} placeholder="搜索标题、Slug 或摘要" className="w-[300px]" />
        <div className="ml-auto">
          <Menu
            width={140}
            trigger={({ toggle }) => (
              <button type="button" onClick={toggle} className={`${actionBtn} flex items-center gap-1.5 font-normal`}>
                {SORT_LABEL[sort]}
                <ChevronDown aria-hidden className="size-3.5" />
              </button>
            )}
            items={(Object.keys(SORT_LABEL) as SortKey[]).map((k) => ({ key: k, label: SORT_LABEL[k], onSelect: () => setSort(k) }))}
          />
        </div>
      </div>
      {!posts ? (
        error ? (
          <StateFeedback kind="error" size="page" title="文章列表加载失败" desc={error} action={<button type="button" onClick={reload} className={actionBtn}>重新加载</button>} />
        ) : (
          <StateFeedback kind="loading" size="page" title="正在加载文章" />
        )
      ) : (
        <>
          {error && <StaleBanner message={`刷新失败：${error}`} onRetry={reload} />}
          {posts.length === 0 ? (
            <StateFeedback
              kind="empty"
              size="page"
              title="还没有文章"
              desc="写下第一篇博客，或导入已有的 Markdown 文件。"
              action={<Button icon={<Plus aria-hidden className="size-3.5" />} onClick={() => navigate('/admin/blog/new')}>写文章</Button>}
            />
          ) : shown.length === 0 ? (
            <StateFeedback
              kind="empty"
              size="page"
              title={keyword.trim() ? `没有找到与「${keyword.trim()}」相关的文章` : '该状态下暂无文章'}
              desc={keyword.trim() ? '换个关键词试试，或清空搜索查看全部文章。' : '切换到「全部」查看其他文章。'}
              action={
                <button type="button" className={actionBtn} onClick={() => (keyword.trim() ? setKeyword('') : setStatus('ALL'))}>
                  {keyword.trim() ? '清空搜索' : '查看全部'}
                </button>
              }
            />
          ) : (
            <>
              <ul aria-busy={loading} className="border-t border-divider">
                {pageItems.map((p) => (
                  <PostRow key={p.id} post={p} onDelete={setDeleting} />
                ))}
              </ul>
              <Pagination page={current} pageSize={PAGE_SIZE} total={shown.length} onChange={setPage} />
            </>
          )}
        </>
      )}
      <DeletePostDialog
        post={deleting}
        onClose={() => setDeleting(null)}
        onDeleted={(id) => {
          setDeleting(null);
          setPosts((l) => l && l.filter((p) => p.id !== id));
        }}
      />
    </AdminColumn>
  );
}
