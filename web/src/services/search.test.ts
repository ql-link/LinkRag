import { db } from '@/mock/db';

import { daysAgo, search, splitHighlight } from './search';

beforeEach(() => {
  db.reset();
  localStorage.clear();
});

describe('search service (mock)', () => {
  it('groups hits and generates a summary when file content matches (B3)', () => {
    const r = search('路线图');
    expect(r.files.map((f) => f.file.name)).toEqual(['Q3 路线图规划.docx', '路线图评审纪要.md', '2026 产品路线图.pdf', '技术路线图_v2.md']);
    expect(r.conversations[0].conversation.title).toBe('Q3 产品路线图要点');
    expect(r.datasets.length).toBe(3);
    expect(r.summary?.citations[0].title).toBe('Q3 路线图规划');
  });

  it('respects dataset / type / time filters and returns nothing for unknown terms (B5)', () => {
    expect(search('路线图', { datasetId: 'ds_2c81e04a', time: 'any', sort: 'relevance' }).files.map((f) => f.file.id)).toEqual(['f_t02']);
    expect(search('路线图', { type: 'PDF', time: 'any', sort: 'relevance' }).files.map((f) => f.file.id)).toEqual(['f_m01']);
    expect(search('路线图', { time: '7d', sort: 'relevance' }).files.every((f) => daysAgo(f.file.updatedAt) <= 7)).toBe(true);
    const none = search('星链计划');
    expect(none.files.length + none.conversations.length + none.datasets.length).toBe(0);
    expect(none.summary).toBeUndefined();
  });

  it('splits text for highlighting case-insensitively', () => {
    expect(splitHighlight('API 鉴权 api', 'api')).toEqual([
      { text: 'API', hit: true },
      { text: ' 鉴权 ', hit: false },
      { text: 'api', hit: true },
    ]);
  });
});
