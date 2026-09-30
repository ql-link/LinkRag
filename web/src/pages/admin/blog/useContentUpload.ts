import { useCallback, useEffect, useRef } from 'react';

import { useToast } from '@/contexts/ToastContext';

import { blogApi, checkImage, errMsg, type BlogPost } from './api';
import type { EBlock } from './blocks';
import { removeBlock, updateBlock } from './editorOps';

type SetBlocks = (updater: (prev: EBlock[]) => EBlock[]) => void;

/**
 * 正文图片上传（设计稿 C9）：先用本地预览占位并标记 uploading，上传 CONTENT_IMAGE 成功后替换为 publicUrl；
 * 失败时移除空的占位块并提示。uploading 的块不会写入正文。
 */
export function useContentUpload(ensurePost: () => Promise<BlogPost>, setBlocks: SetBlocks) {
  const toast = useToast();
  const previews = useRef(new Set<string>());
  useEffect(() => () => previews.current.forEach((u) => URL.revokeObjectURL(u)), []);

  return useCallback(
    (blockId: string, file: File) => {
      const bad = checkImage(file);
      if (bad) {
        toast(bad, { tone: 'error' });
        setBlocks((l) => {
          const b = l.find((x) => x.id === blockId);
          return b?.t === 'img' && !b.src ? removeBlock(l, blockId) : l;
        });
        return;
      }
      const preview = URL.createObjectURL(file);
      previews.current.add(preview);
      let previous = '';
      setBlocks((l) => {
        const b = l.find((x) => x.id === blockId);
        if (b?.t === 'img') previous = b.src;
        return updateBlock(l, blockId, { src: preview, uploading: true, ...(b?.t === 'img' && !b.alt ? { alt: file.name.replace(/\.\w+$/, '') } : {}) });
      });
      void (async () => {
        try {
          const p = await ensurePost();
          const asset = await blogApi.upload(p.id, 'CONTENT_IMAGE', file);
          setBlocks((l) => updateBlock(l, blockId, { src: asset.publicUrl, uploading: false }));
        } catch (e) {
          toast(`图片上传失败：${errMsg(e)}`, { tone: 'error' });
          setBlocks((l) => (previous ? updateBlock(l, blockId, { src: previous, uploading: false }) : removeBlock(l, blockId)));
        } finally {
          URL.revokeObjectURL(preview);
          previews.current.delete(preview);
        }
      })();
    },
    [ensurePost, setBlocks, toast],
  );
}
