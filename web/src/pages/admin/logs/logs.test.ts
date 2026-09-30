import { describe, expect, it } from 'vitest';

import { buildLogQuery, fmtClock, fmtSpan, logsApi, parseLogTime, parseRange, rangeWindow } from './api';
import { countLevels, filterCount, filtersFromSearch, filtersToSearch, maxPage, pageInfo, toQuery } from './logic';
import { traceSteps } from './TraceTimeline';

const NOW = new Date('2026-09-29T06:30:00Z').getTime();

describe('time range', () => {
  it('maps range to start/end ending at now', () => {
    expect(rangeWindow('2h', NOW)).toEqual({ start: new Date(NOW - 2 * 3600_000), end: new Date(NOW) });
    expect(rangeWindow('7d', NOW).start.getTime()).toBe(NOW - 7 * 86_400_000);
  });
  it('falls back to 2h for unknown values', () => {
    expect(parseRange('24h')).toBe('24h');
    expect(parseRange('1y')).toBe('2h');
    expect(parseRange(null)).toBe('2h');
  });
});

describe('query params', () => {
  it('builds snake_case params, trims blanks and clamps page_size', () => {
    const q = buildLogQuery({ service: ' ', level: 'error', traceId: ' abc ', keyword: '', start: new Date(NOW), page: 0, pageSize: 500 });
    expect(q).toEqual({ service: undefined, level: 'ERROR', trace_id: 'abc', keyword: undefined, start_time: new Date(NOW).toISOString(), end_time: undefined, page: 1, page_size: 200 });
  });
  it('turns filters into a query with the computed window', () => {
    const q = toQuery({ service: 'tolink-rag', level: '', traceId: '', keyword: 'milvus', range: '24h' }, 2, 50, NOW);
    expect(q.start).toEqual(new Date(NOW - 86_400_000));
    expect(q.end).toEqual(new Date(NOW));
    expect(buildLogQuery(q)).toMatchObject({ service: 'tolink-rag', keyword: 'milvus', page: 2, page_size: 50, end_time: '2026-09-29T06:30:00.000Z' });
  });
});

describe('deep links', () => {
  it('reads and round-trips url params', () => {
    const f = filtersFromSearch(new URLSearchParams('trace_id=7f3a&level=warn&service=tolink-rag&range=7d'));
    expect(f).toEqual({ service: 'tolink-rag', level: 'WARN', traceId: '7f3a', keyword: '', range: '7d' });
    expect(filterCount(f)).toBe(3);
    expect(filtersToSearch(f).toString()).toBe('service=tolink-rag&level=WARN&trace_id=7f3a&range=7d');
    expect(filtersToSearch({ ...f, service: '', level: '', traceId: '', range: '2h' }).toString()).toBe('');
  });
});

describe('pagination within the 1000-line cap', () => {
  it('limits page count', () => {
    expect(maxPage(50)).toBe(20);
    expect(maxPage(200)).toBe(5);
  });
  it('labels totals honestly', () => {
    expect(pageInfo(37, 1, 50)).toMatchObject({ totalLabel: '37', exact: true, hasNext: false, knownPages: 1 });
    expect(pageInfo(100, 2, 50)).toMatchObject({ totalLabel: '≥ 100', exact: false, hasNext: true });
    expect(pageInfo(1000, 20, 50)).toMatchObject({ totalLabel: '1,000+', capped: true, hasNext: false });
  });
});

describe('helpers', () => {
  it('counts levels on the current page', () => {
    expect(countLevels([{ level: 'ERROR' }, { level: 'FATAL' }, { level: 'WARN' }, { level: 'INFO' }, { level: null }])).toEqual({ error: 2, warn: 1 });
  });
  it('parses loguru time repr and formats', () => {
    const d = parseLogTime('2026-09-29 14:32:08.412345+08:00')!;
    expect(d.toISOString()).toBe('2026-09-29T06:32:08.412Z');
    expect(fmtClock('2026-09-29T06:32:08.412Z', new Date('2026-09-29T06:40:00Z'))).toMatch(/:32:08\.412$/);
    expect(fmtSpan(820)).toBe('820ms');
    expect(fmtSpan(3300)).toBe('3.3s');
  });
  it('orders trace steps by time with offsets', () => {
    const base = { level: 'INFO', service: 'a', host: null, pid: null, trace_id: 't', logger_name: null, message: null, exception: null };
    const s = traceSteps([
      { ...base, time: '2026-09-29T06:32:08.412Z' },
      { ...base, service: 'b', time: '2026-09-29T06:32:05.103Z' },
    ]);
    expect(s.rows.map((r) => r.index)).toEqual([1, 0]);
    expect(s.span).toBe(3309);
    expect(s.services).toEqual(['b', 'a']);
  });
});

describe('mock api', () => {
  it('filters by trace_id and caps total at 1000', async () => {
    const all = await logsApi.query({ start: new Date(Date.now() - 7 * 86_400_000), end: new Date(), page: 5, pageSize: 200 });
    expect(all.total).toBe(1000);
    const first = all.items[0];
    const tr = await logsApi.query({ traceId: first.trace_id!, start: new Date(Date.now() - 7 * 86_400_000), end: new Date() });
    expect(tr.items.length).toBeGreaterThan(0);
    expect(tr.items.every((i) => i.trace_id === first.trace_id)).toBe(true);
  });
});
