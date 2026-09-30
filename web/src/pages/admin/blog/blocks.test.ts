import { describe, expect, it } from 'vitest';

import { fromMarkdown, toMarkdown } from '@/pages/blog/markdown';
import { AUTHOR, STATIC_POSTS } from '@/pages/blog/posts';

import { countChars, parseDoc, serializeDoc, type EBlock } from './blocks';
import { readMeta, writeMeta } from './frontMatter';

const strip = (bs: EBlock[]) => bs.map(({ id: _id, ...rest }) => rest);

const SAMPLE = `---
category: 评测
tags: [重排, Recall]
figures:
  - Recall@10 | 90.20% | 说明
---

# 标题会被官网忽略

## 为什么只用向量检索不够 {#why}

稠密向量擅长语义相似，但对**专有名词**并不敏感。
第二行仍属于同一段落，含 \`Top-5\` 与 [链接](https://x.cn/a)。

> 向量负责“意思相近”。

> **注意** RRF 的常数 k 通常取 60。

### 小节

1. 同时执行两路检索
2. 用 RRF 合并

- 无序一
- 无序二

\`\`\`python
def f(x):

    return x
\`\`\`

\`\`\`setup
模型: bge-m3
\`\`\`

![图 1 · 召回率](https://cdn.x/recall.png)

| 检索方式 | Top-5 召回 |
| --- | --- |
| 稠密向量 | 78.2% |
| BM25 | 64.5% |
: 三个知识库的平均值
`;

describe('block serializer', () => {
  it('parses every block type', () => {
    const doc = parseDoc(SAMPLE);
    expect(doc.frontMatter?.startsWith('---\ncategory: 评测')).toBe(true);
    expect(doc.blocks.map((b) => b.t)).toEqual(['h', 'h', 'p', 'quote', 'callout', 'h', 'list', 'list', 'code', 'code', 'img', 'table']);
    expect(doc.blocks[1]).toMatchObject({ level: 2, text: '为什么只用向量检索不够', anchor: 'why' });
    expect(doc.blocks[6]).toMatchObject({ ordered: true, items: ['同时执行两路检索', '用 RRF 合并'] });
    expect(doc.blocks[8]).toMatchObject({ lang: 'python', text: 'def f(x):\n\n    return x' });
    expect(doc.blocks[11]).toMatchObject({ head: ['检索方式', 'Top-5 召回'], rows: [['稠密向量', '78.2%'], ['BM25', '64.5%']], caption: '三个知识库的平均值' });
  });

  it('round-trips markdown → blocks → markdown → blocks', () => {
    const once = serializeDoc(parseDoc(SAMPLE));
    const twice = serializeDoc(parseDoc(once));
    expect(twice).toBe(once);
    expect(strip(parseDoc(once).blocks)).toEqual(strip(parseDoc(SAMPLE).blocks));
    expect(once.startsWith('---\ncategory: 评测\ntags: [重排, Recall]\nfigures:\n  - Recall@10 | 90.20% | 说明\n---\n')).toBe(true);
  });

  it('keeps output compatible with the public blog renderer', () => {
    for (const p of STATIC_POSTS) {
      const md = serializeDoc(parseDoc(toMarkdown(p)));
      const back = fromMarkdown({ slug: p.slug, title: p.title, summary: p.lead, coverPublicUrl: null, publishedAt: `${p.date}T09:00:00`, contentMarkdown: md }, AUTHOR.name);
      expect(JSON.parse(JSON.stringify(back))).toEqual(JSON.parse(JSON.stringify(p)));
    }
  });

  it('drops blank and uploading blocks and handles empty input', () => {
    expect(serializeDoc(parseDoc(''))).toBe('');
    const doc = parseDoc('正文');
    doc.blocks.push({ id: 'x', t: 'p', text: '  ' }, { id: 'y', t: 'img', alt: 'a', src: 'blob:1', uploading: true });
    expect(serializeDoc(doc)).toBe('正文\n');
  });

  it('escapes pipes in table cells and counts characters', () => {
    const doc = { frontMatter: null, blocks: [{ id: 't', t: 'table', head: ['a|b', 'c'], rows: [['1', '2']] } as EBlock] };
    expect(serializeDoc(doc)).toBe('| a\\|b | c |\n| --- | --- |\n| 1 | 2 |\n');
    expect(countChars(parseDoc('## 标题\n\n**粗体** 文字'))).toBe(6);
  });
});

describe('front matter meta', () => {
  it('updates category and tags while preserving other keys', () => {
    const fm = '---\ncategory: 评测\ntags: [a, b]\nfigures:\n  - x | 1 | y\n---';
    expect(readMeta(fm)).toEqual({ category: '评测', tags: ['a', 'b'] });
    expect(writeMeta(fm, { category: '实践', tags: ['c'] })).toBe('---\ncategory: 实践\ntags: [c]\nfigures:\n  - x | 1 | y\n---');
    expect(writeMeta(null, { category: '', tags: [] })).toBeNull();
    expect(writeMeta(null, { category: '技术', tags: ['x'] })).toBe('---\ncategory: 技术\ntags: [x]\n---');
  });
});
