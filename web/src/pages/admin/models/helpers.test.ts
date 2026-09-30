import { describe, expect, it } from 'vitest';

import type { SyncCandidate } from './api';
import { groupCandidates, parseJsonish, parseModalities, prettyMetadata, tokens } from './helpers';

const cand = (p: Partial<SyncCandidate>): SyncCandidate => ({ id: 1, capability: 'CHAT', providerId: 1, modelName: 'm', lastSeenAt: '2026-09-01T00:00:00', ...p }) as SyncCandidate;

describe('metadata parsing', () => {
  it('handles JSON strings, objects and garbage', () => {
    expect(parseJsonish('{"a":1}')).toEqual({ a: 1 });
    expect(parseJsonish({ a: 1 })).toEqual({ a: 1 });
    expect(parseJsonish('not json')).toBe('not json');
    expect(parseJsonish('')).toBeNull();
    expect(parseJsonish(undefined)).toBeNull();
    expect(prettyMetadata('{"a":1}')).toBe('{\n  "a": 1\n}');
  });
  it('parses modalities', () => {
    expect(parseModalities('["text","image"]')).toEqual(['text', 'image']);
    expect(parseModalities(['text'])).toEqual(['text']);
    expect(parseModalities('text, audio')).toEqual(['text', 'audio']);
    expect(parseModalities(null)).toEqual([]);
  });
});

describe('groupCandidates', () => {
  it('groups by provider+model and orders by latest seen', () => {
    const g = groupCandidates([
      cand({ id: 1, modelName: 'a', capability: 'VISION', lastSeenAt: '2026-09-01' }),
      cand({ id: 2, modelName: 'b', lastSeenAt: '2026-09-03' }),
      cand({ id: 3, modelName: 'a', capability: 'CHAT', lastSeenAt: '2026-09-02' }),
      cand({ id: 4, modelName: 'a', providerId: 2, lastSeenAt: '2026-08-01' }),
    ]);
    expect(g.map((x) => x.key)).toEqual(['1:b', '1:a', '2:a']);
    expect(g[1].items.map((c) => c.id)).toEqual([3, 1]);
  });
});

it('formats token counts', () => {
  expect(tokens(128000)).toBe('128K');
  expect(tokens(1_000_000)).toBe('1M');
  expect(tokens(null)).toBe('—');
});

describe('groupByModelName', () => {
  it('keeps first-seen order', async () => {
    const { groupByModelName } = await import('./helpers');
    const g = groupByModelName([{ modelName: 'b', c: 1 }, { modelName: 'a', c: 2 }, { modelName: 'b', c: 3 }]);
    expect(g.map((x) => [x.modelName, x.items.length])).toEqual([['b', 2], ['a', 1]]);
  });
});

it('formats job duration', async () => {
  const { duration } = await import('./helpers');
  expect(duration('2026-09-29T09:40:00', '2026-09-29T09:40:04.200')).toBe('4.2s');
  expect(duration('2026-09-29T09:40:00', '2026-09-29T09:41:12')).toBe('1m 12s');
  expect(duration('2026-09-29T09:40:00', null)).toBe('—');
});
