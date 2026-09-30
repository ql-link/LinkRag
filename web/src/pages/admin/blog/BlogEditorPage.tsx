import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { useToast } from '@/contexts/ToastContext';

import { actionBtn, StateFeedback } from '../StateFeedback';
import { blogApi, errMsg, type BlogAsset } from './api';
import { BlockEditor } from './BlockEditor';
import { block, countChars, isBlank, parseDoc, serializeDoc, type EBlock } from './blocks';
import { CoverDialog } from './CoverDialog';
import { coverUrl } from './CoverThumb';
import { DeletePostDialog } from './DeletePostDialog';
import { DocumentHead } from './DocumentHead';
import { EditorAside } from './EditorAside';
import { EditorTopbar, type Mode } from './EditorTopbar';
import { IllustrationLibrary } from './IllustrationLibrary';
import { PublishDialog } from './PublishDialog';
import { SourceEditor } from './SourceEditor';
import { StatusBar } from './StatusBar';
import { useContentUpload } from './useContentUpload';
import { useEditorShortcuts } from './useEditorShortcuts';
import { usePostEditor } from './usePostEditor';

type DialogKind = 'cover' | 'library' | 'publish' | 'delete' | null;

/** 设计稿 C3–C11 文章编辑器；`/admin/blog/new` 为新建，首次保存或上传图片时创建草稿 */
export default function BlogEditorPage() {
  const { postId = 'new' } = useParams();
  const isNew = postId === 'new';
  const numericId = isNew ? null : Number(postId);
  const navigate = useNavigate();
  const toast = useToast();
  const ed = usePostEditor(numericId !== null && Number.isFinite(numericId) ? numericId : null);
  const { post, draft, setDraft } = ed;
  const [mode, setMode] = useState<Mode>('wysiwyg');
  const [source, setSource] = useState('');
  const [cursor, setCursor] = useState<{ line: number; col: number } | null>(null);
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [statusBusy, setStatusBusy] = useState(false);
  const [cover, setCover] = useState<string | null>(null);
  const importRef = useRef<HTMLInputElement>(null);

  // 新建后把地址切换为真实 id（不重新加载）
  useEffect(() => {
    if (isNew && post) navigate(`/admin/blog/${post.id}`, { replace: true });
  }, [isNew, post, navigate]);
  useEffect(() => {
    if (!post?.coverAssetId) return setCover(null);
    let alive = true;
    void coverUrl(post).then((u) => alive && setCover(u));
    return () => {
      alive = false;
    };
  }, [post?.id, post?.coverAssetId]); // eslint-disable-line react-hooks/exhaustive-deps

  const setBlocks = useCallback((fn: (prev: EBlock[]) => EBlock[]) => setDraft((d) => ({ ...d, doc: { ...d.doc, blocks: fn(d.doc.blocks) } })), [setDraft]);
  const upload = useContentUpload(ed.ensurePost, setBlocks);

  const toggleMode = useCallback(
    (next?: Mode) => {
      const target = next ?? (mode === 'source' ? 'wysiwyg' : 'source');
      if (target === mode) return;
      if (target === 'source') setSource(ed.markdown);
      else setDraft((d) => (d.doc.blocks.length ? d : { ...d, doc: { ...d.doc, blocks: [block({ t: 'p', text: '' })] } }));
      setMode(target);
    },
    [mode, ed.markdown, setDraft],
  );

  const onSource = (v: string) => {
    setSource(v);
    setDraft((d) => ({ ...d, doc: parseDoc(v) }));
  };

  /** 返回保存后的文章；失败返回 null */
  const save = useCallback(async (quiet = false) => {
    if (draft.doc.blocks.some((b) => b.t === 'img' && b.uploading)) {
      toast('图片仍在上传，请稍后再保存');
      return null;
    }
    try {
      const p = await ed.save();
      if (!quiet) toast('已保存修改', { tone: 'success' });
      return p;
    } catch (e) {
      toast(errMsg(e, '保存失败'), { tone: 'error' });
      return null;
    }
  }, [ed, draft.doc.blocks, toast]);

  useEditorShortcuts({ dirty: ed.dirty, onSave: () => void (ed.saving || save()), onToggleMode: () => toggleMode() });

  const publish = async () => {
    let id = post?.id;
    if (ed.dirty || !post || !ed.savedMarkdown.trim()) {
      const saved = await save(true);
      if (!saved) return;
      id = saved.id;
    }
    try {
      await ed.setStatus('publish', id);
      toast('文章已发布', { tone: 'success' });
      setDialog(null);
    } catch (e) {
      toast(errMsg(e, '发布失败'), { tone: 'error' });
    }
  };

  const unpublish = async () => {
    setStatusBusy(true);
    try {
      await ed.setStatus('unpublish');
      toast('文章已下架，官网不再展示');
    } catch (e) {
      toast(errMsg(e, '下架失败'), { tone: 'error' });
    } finally {
      setStatusBusy(false);
    }
  };

  const importMd = async (file: File | undefined) => {
    if (!file) return;
    if (!/\.(md|markdown)$/i.test(file.name)) return toast('请选择 .md 或 .markdown 文件', { tone: 'error' });
    if (ed.dirty && !window.confirm('导入会覆盖当前正文，未保存的修改将丢失。继续吗？')) return;
    try {
      const p = await ed.ensurePost();
      await blogApi.importMarkdown(p.id, file);
      ed.replaceFromServer(await blogApi.get(p.id));
      setMode('wysiwyg');
      toast('已导入 Markdown', { tone: 'success' });
    } catch (e) {
      toast(errMsg(e, '导入失败'), { tone: 'error' });
    }
  };

  const insertAsset = (a: BlogAsset) => {
    const img = block({ t: 'img', alt: a.originalFilename.replace(/\.\w+$/, ''), src: a.publicUrl });
    if (mode === 'source') onSource(`${source.replace(/\s*$/, '')}\n\n![${img.t === 'img' ? img.alt : ''}](${a.publicUrl})\n`);
    else setBlocks((l) => (l.length && ['p', 'md'].includes(l[l.length - 1].t) && isBlank(l[l.length - 1]) ? [...l.slice(0, -1), img] : [...l, img]));
    toast('已插入正文末尾', { tone: 'success' });
  };

  const back = () => {
    if (ed.dirty && !window.confirm('有未保存的修改，确定离开吗？')) return;
    navigate('/admin/blog');
  };

  if (!isNew && ed.loadError)
    return ed.loadError === 'NOT_FOUND' ? (
      <StateFeedback kind="empty" size="page" title="文章不存在" desc="它可能已被删除。" action={<Link to="/admin/blog" className={actionBtn}>返回文章列表</Link>} />
    ) : (
      <StateFeedback kind="error" size="page" title="文章加载失败" desc={ed.loadError} action={<button type="button" onClick={ed.reload} className={actionBtn}>重新加载</button>} />
    );
  if (!isNew && (ed.loading || !post)) return <StateFeedback kind="loading" size="page" title="正在打开文章" />;

  const first = draft.doc.blocks[0];
  return (
    <div className="flex min-h-full flex-col">
      <input ref={importRef} type="file" accept=".md,.markdown,text/markdown" hidden onChange={(e) => (void importMd(e.target.files?.[0]), (e.target.value = ''))} />
      <EditorTopbar
        post={post}
        isNew={isNew && !post}
        dirty={ed.dirty}
        saving={ed.saving}
        savedAt={ed.savedAt}
        mode={mode}
        onMode={toggleMode}
        onBack={back}
        onImport={() => importRef.current?.click()}
        onLibrary={() => setDialog('library')}
        onSave={() => void save()}
        onPublish={() => setDialog('publish')}
        onUnpublish={() => void unpublish()}
        onDelete={() => setDialog('delete')}
        statusBusy={statusBusy}
      />
      <div className="flex flex-1 justify-center gap-10 px-10 pt-10">
        <div className="w-full max-w-[680px] min-w-0">
          <DocumentHead
            post={post}
            coverUrl={cover}
            title={draft.title}
            summary={draft.summary}
            onTitle={(title) => setDraft((d) => ({ ...d, title }))}
            onSummary={(summary) => setDraft((d) => ({ ...d, summary }))}
            onCover={() => setDialog('cover')}
            firstBlockKey={first ? (first.t === 'table' ? `${first.id}:0` : first.id) : null}
          />
          <div className="mt-6">
            {mode === 'source' ? <SourceEditor value={source} onChange={onSource} onCursor={(line, col) => setCursor({ line, col })} /> : <BlockEditor blocks={draft.doc.blocks} onChange={setBlocks} onUpload={upload} />}
          </div>
        </div>
        <EditorAside blocks={draft.doc.blocks} frontMatter={draft.doc.frontMatter} showOutline={mode === 'wysiwyg'} onFrontMatter={(fm) => (mode === 'source' ? onSource(serializeDoc({ ...draft.doc, frontMatter: fm })) : setDraft((d) => ({ ...d, doc: { ...d.doc, frontMatter: fm } })))} />
      </div>
      <StatusBar mode={mode} chars={countChars(draft.doc)} cursor={cursor} />

      <CoverDialog
        open={dialog === 'cover'}
        onClose={() => setDialog(null)}
        post={post}
        ensurePost={ed.ensurePost}
        onCoverChange={(id, url) => {
          setCover(url);
          ed.setPost((p) => p && { ...p, coverAssetId: id });
        }}
      />
      <IllustrationLibrary open={dialog === 'library'} onClose={() => setDialog(null)} post={post} ensurePost={ed.ensurePost} markdown={ed.markdown} onInsert={insertAsset} />
      <PublishDialog open={dialog === 'publish'} onClose={() => setDialog(null)} post={post} title={draft.title} summary={draft.summary} markdown={ed.markdown} dirty={ed.dirty} onConfirm={publish} />
      <DeletePostDialog post={dialog === 'delete' ? post : null} onClose={() => setDialog(null)} onDeleted={() => navigate('/admin/blog', { replace: true })} />
    </div>
  );
}
