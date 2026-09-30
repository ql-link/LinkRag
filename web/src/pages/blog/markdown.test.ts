import { describe, expect, it } from 'vitest';

import { fromMarkdown, toMarkdown } from './markdown';
import { AUTHOR, STATIC_POSTS } from './posts';

const remote = (p: (typeof STATIC_POSTS)[number], md: string) => ({ slug: p.slug, title: p.title, summary: p.lead, coverPublicUrl: null, publishedAt: `${p.date}T09:00:00`, contentMarkdown: md });

describe('blog markdown', () => {
  it.each(STATIC_POSTS.map((p) => [p.slug, p] as const))('round-trips %s', (_, p) => {
    const back = fromMarkdown(remote(p, toMarkdown(p)), AUTHOR.name);
    expect(JSON.parse(JSON.stringify(back))).toEqual(JSON.parse(JSON.stringify(p)));
  });

  it('parses plain markdown without front matter', () => {
    const post = fromMarkdown({ slug: 'a'.repeat(32), title: 'T', summary: null, coverPublicUrl: 'https://x/c.png', publishedAt: '2026-10-01T08:00:00', contentMarkdown: '# T\n\n开场白。\n\n## 第一节\n\n正文 `x`。\n\n![示意图](https://x/a.png)' }, '团队');
    expect(post.category).toBe('技术');
    expect(post.lead).toBe('开场白。');
    expect(post.cover.image).toBe('https://x/c.png');
    expect(post.sections.map((s) => s.title)).toEqual(['导语', '第一节']);
    expect(post.sections[1].blocks[1]).toEqual({ t: 'img', alt: '示意图', src: 'https://x/a.png' });
  });
});
