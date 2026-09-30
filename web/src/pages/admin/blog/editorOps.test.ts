import { describe, expect, it } from 'vitest';

import { fromMd, parseBody, serializeDoc, toMd, type EBlock } from './blocks';
import { mdEnter, outline, referencedUrls, setHeadingLevel, settle, starter } from './editorOps';

const strip = (bs: EBlock[]) => bs.map(({ id: _id, ...rest }) => rest);

describe('source-mode blocks', () => {
  it('parses headings 1–6, rules and empty headings', () => {
    expect(strip(parseBody('# 一\n\n###### 六\n\n---\n\n#'))).toEqual([
      { t: 'h', level: 1, text: '一' },
      { t: 'h', level: 6, text: '六' },
      { t: 'hr' },
      { t: 'h', level: 1, text: '' },
    ]);
    expect(strip(parseBody('#标签'))).toEqual([{ t: 'p', text: '#标签' }]);
  });

  it('round-trips a block through source mode', () => {
    const [h] = parseBody('## 标题 {#a}');
    const md = toMd(h);
    expect(md).toEqual({ id: h.id, t: 'md', src: '## 标题 {#a}' });
    expect(fromMd(md)).toEqual([h]);
  });

  it('splits source that became several blocks and keeps the first id', () => {
    const out = fromMd({ id: 'x', t: 'md', src: '# 标题\n正文第一行\n\n- a\n- b' });
    expect(out[0]).toMatchObject({ id: 'x', t: 'h', level: 1, text: '标题' });
    expect(strip(out.slice(1))).toEqual([
      { t: 'p', text: '正文第一行' },
      { t: 'list', ordered: false, items: ['a', 'b'] },
    ]);
    expect(fromMd({ id: 'y', t: 'md', src: '  ' })).toEqual([{ id: 'y', t: 'p', text: '' }]);
  });

  it('serializes documents that still contain a source block', () => {
    const doc = { frontMatter: null, blocks: [{ id: 'a', t: 'md', src: '# 你好' } as EBlock, { id: 'b', t: 'hr' } as EBlock, { id: 'c', t: 'md', src: '' } as EBlock] };
    expect(serializeDoc(doc)).toBe('# 你好\n\n---\n');
    expect(settle(doc.blocks, 'c').map((b) => b.t)).toEqual(['h', 'hr', 'md']);
    expect(outline(doc.blocks)).toEqual([{ id: 'a', level: 1, text: '你好' }]);
  });

  it('starts new text blocks in source mode', () => {
    expect(starter({ t: 'h', level: 2, text: '' })).toEqual({ t: 'md', src: '## ' });
    expect(starter({ t: 'list', ordered: true, items: [''] })).toEqual({ t: 'md', src: '1. ' });
    expect(starter({ t: 'quote', text: '' })).toEqual({ t: 'md', src: '> ' });
    expect(starter({ t: 'code', lang: '', text: '' })).toEqual({ t: 'code', lang: '', text: '' });
  });
});

describe('enter in source mode', () => {
  it('splits paragraphs and continues lists and quotes', () => {
    expect(mdEnter('前后', 1)).toEqual({ kind: 'split', before: '前', after: '后' });
    expect(mdEnter('- a', 3)).toEqual({ kind: 'insert', text: '- a\n- ', caret: 6 });
    expect(mdEnter('2. b', 4)).toEqual({ kind: 'insert', text: '2. b\n3. ', caret: 8 });
    expect(mdEnter('> q', 3)).toEqual({ kind: 'insert', text: '> q\n> ', caret: 6 });
  });

  it('exits on an empty item', () => {
    expect(mdEnter('- a\n- ', 6)).toEqual({ kind: 'exit', before: '- a', after: '' });
    expect(mdEnter('- ', 2)).toEqual({ kind: 'exit', before: '', after: '' });
  });

  it('turns fences, rules and table rows into blocks', () => {
    expect(mdEnter('```ts', 5)).toEqual({ kind: 'code', lang: 'ts' });
    expect(mdEnter('---', 3)).toEqual({ kind: 'hr' });
    expect(mdEnter('| a | b |', 9)).toEqual({ kind: 'table', head: ['a', 'b'] });
  });

  it('changes heading level', () => {
    expect(setHeadingLevel('正文', 1)).toBe('# 正文');
    expect(setHeadingLevel('### 小节', 2)).toBe('## 小节');
    expect(setHeadingLevel('## 小节', 0)).toBe('小节');
  });

  it('collects referenced image urls', () => {
    expect([...referencedUrls('a ![x](https://a/1.png)\n![](https://a/2.png)')]).toEqual(['https://a/1.png', 'https://a/2.png']);
  });
});
