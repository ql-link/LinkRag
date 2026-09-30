/** 编辑器状态：加载文章、文档块、脏状态、保存（PATCH 标题/摘要 + PUT 正文）、发布与下线 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { blogApi, type BlogPost } from './api';
import { block, parseDoc, serializeDoc, type Doc } from './blocks';

export interface Draft {
  title: string;
  summary: string;
  doc: Doc;
}

const emptyDoc = (): Doc => ({ frontMatter: null, blocks: [block({ t: 'p', text: '' })] });

function toDraft(p: BlogPost): Draft {
  const doc = parseDoc(p.contentMarkdown ?? '');
  return { title: p.title, summary: p.summary ?? '', doc: doc.blocks.length ? doc : { ...doc, blocks: emptyDoc().blocks } };
}

const snapshot = (d: Draft) => JSON.stringify([d.title.trim(), d.summary.trim(), serializeDoc(d.doc)]);

export function usePostEditor(postId: number | null) {
  const [post, setPost] = useState<BlogPost | null>(null);
  const [draft, setDraft] = useState<Draft>({ title: '', summary: '', doc: emptyDoc() });
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(postId !== null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const saved = useRef(snapshot({ title: '', summary: '', doc: emptyDoc() }));
  /** 服务端已保存的正文（发布前需有已保存的正文） */
  const [savedMarkdown, setSavedMarkdown] = useState('');

  /** 已载入 / 刚创建的文章 id：新建后路由从 new 切到真实 id 时不重复加载，避免覆盖未保存内容 */
  const loadedId = useRef<number | null>(null);

  const load = useCallback(() => {
    if (postId === null || loadedId.current === postId) return;
    setLoading(true);
    blogApi
      .get(postId)
      .then((p) => {
        const d = toDraft(p);
        loadedId.current = p.id;
        setPost(p);
        setDraft(d);
        saved.current = snapshot(d);
        setSavedMarkdown(p.contentMarkdown ?? '');
        setLoadError(null);
      })
      .catch((e: Error & { status?: number }) => setLoadError(e.status === 404 ? 'NOT_FOUND' : e.message || '加载失败'))
      .finally(() => setLoading(false));
  }, [postId]);
  useEffect(load, [load]);

  const markdown = useMemo(() => serializeDoc(draft.doc), [draft.doc]);
  const dirty = snapshot(draft) !== saved.current;

  /** 新文章：首次保存 / 上传图片时创建草稿（并发调用只创建一次）；返回文章 */
  const creating = useRef<Promise<BlogPost> | null>(null);
  const latest = useRef({ post, title: draft.title, summary: draft.summary });
  latest.current = { post, title: draft.title, summary: draft.summary };
  const ensurePost = useCallback(async (): Promise<BlogPost> => {
    const { post: cur, title, summary } = latest.current;
    if (cur) return cur;
    creating.current ??= blogApi.create({ title: title.trim() || '未命名文章', summary: summary.trim() || undefined }).then((created) => {
      loadedId.current = created.id;
      latest.current.post = created;
      setPost(created);
      return created;
    });
    try {
      return await creating.current;
    } catch (e) {
      creating.current = null;
      throw e;
    }
  }, []);

  /** 保存；正文为空时后端拒绝 PUT，只保存标题与摘要。返回保存后的文章 */
  const save = useCallback(async (): Promise<BlogPost> => {
    setSaving(true);
    try {
      const current = draft;
      let p = await ensurePost();
      const title = current.title.trim() || '未命名文章';
      const summary = current.summary.trim() || null;
      if (title !== p.title || summary !== (p.summary ?? null)) p = await blogApi.update(p.id, { title, summary });
      const md = serializeDoc(current.doc);
      if (md.trim() && md !== savedMarkdown) {
        p = await blogApi.saveContent(p.id, md);
        setSavedMarkdown(md);
      }
      setPost((old) => ({ ...p, contentMarkdown: md.trim() ? md : (old?.contentMarkdown ?? null) }));
      saved.current = snapshot(current);
      setSavedAt(new Date());
      return p;
    } finally {
      setSaving(false);
    }
  }, [draft, ensurePost, savedMarkdown]);

  const setStatus = useCallback(async (action: 'publish' | 'unpublish', id = latest.current.post?.id) => {
    if (!id) throw new Error('请先保存文章');
    const p = await (action === 'publish' ? blogApi.publish(id) : blogApi.unpublish(id));
    setPost((old) => ({ ...(old ?? p), ...p }));
    return p;
  }, []);

  /** 导入 Markdown 后以服务端正文为准重新载入 */
  const replaceFromServer = useCallback((p: BlogPost) => {
    const d = toDraft(p);
    setPost(p);
    setDraft(d);
    saved.current = snapshot(d);
    setSavedMarkdown(p.contentMarkdown ?? '');
  }, []);

  return { post, setPost, draft, setDraft, markdown, savedMarkdown, dirty, loading, loadError, reload: load, saving, savedAt, save, ensurePost, setStatus, replaceFromServer };
}

export type PostEditor = ReturnType<typeof usePostEditor>;
