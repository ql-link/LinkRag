import { useEffect, useState } from 'react';

import { cn } from '@/lib/cn';

import { CATEGORIES, parseTags, readMeta, writeMeta } from './frontMatter';

/** 文章设置：分类与标签写入正文 front matter（官网据此展示） */
export function MetaPanel({ frontMatter, onChange }: { frontMatter: string | null; onChange: (fm: string | null) => void }) {
  const meta = readMeta(frontMatter);
  const [tagText, setTagText] = useState(meta.tags.join('，'));
  const tagsKey = meta.tags.join('\u0000');
  useEffect(() => setTagText(meta.tags.join('，')), [tagsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const commitTags = () => {
    const tags = parseTags(tagText);
    if (tags.join('\u0000') !== tagsKey) onChange(writeMeta(frontMatter, { ...meta, tags }));
  };

  return (
    <section aria-label="文章设置" className="flex flex-col gap-3">
      <p className="text-[11px] text-muted">分类</p>
      <div className="flex flex-wrap gap-1.5">
        {CATEGORIES.map((c) => {
          const on = (meta.category || '技术') === c;
          return (
            <button
              key={c}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(writeMeta(frontMatter, { ...meta, category: c }))}
              className={cn('rounded-full border px-2.5 py-[3px] text-[11.5px] transition-colors', on ? 'border-transparent bg-active font-medium text-ink' : 'border-line text-text2 hover:bg-soft')}
            >
              {c}
            </button>
          );
        })}
      </div>
      <label className="flex flex-col gap-1.5">
        <span className="text-[11px] text-muted">标签</span>
        <input
          value={tagText}
          onChange={(e) => setTagText(e.target.value)}
          onBlur={commitTags}
          onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), commitTags())}
          placeholder="用逗号分隔，如：重排，Recall"
          className="rounded-[7px] border border-line bg-white px-2.5 py-1.5 text-[12px] text-ink outline-none focus:border-ink"
        />
      </label>
      {meta.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {meta.tags.map((t) => (
            <span key={t} className="rounded-[5px] bg-soft px-1.5 py-0.5 text-[11px] text-text2">
              #{t}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
