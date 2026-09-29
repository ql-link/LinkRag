import { detectPreset, formatRange, parseCompactDate, presetRange, recentCalls, usageReport } from './usage';

describe('usage service (mock)', () => {
  it('reproduces the E1 design figures for the last 7 days', () => {
    const range = presetRange('7d');
    expect(formatRange(range)).toBe('2026-09-21 — 09-27');
    const r = usageReport(range);
    expect(r.totals.tokens).toBe(1_284_562);
    expect(r.totals.calls).toBe(3146);
    expect(r.change?.tokens).toBeCloseTo(0.184, 3);
    expect(r.change?.calls).toBeCloseTo(0.092, 3);
    expect(r.trend.map((t) => t.label)).toEqual(['09-21', '09-22', '09-23', '09-24', '09-25', '09-26', '09-27']);
    expect(r.trend.at(-1)?.tokens).toBe(261_000);
  });

  it('lists the most recent calls first, matching the design rows', () => {
    const calls = recentCalls(presetRange('7d'), 5);
    expect(calls.map((c) => c.time.slice(11))).toEqual(['14:32:08', '14:31:55', '14:20:11', '14:18:47', '13:59:02']);
    expect(calls.map((c) => c.status)).toEqual(['ok', 'ok', 'timeout', 'ok', 'quota']);
    const more = recentCalls(presetRange('7d'), 60);
    expect(more.every((c, i) => i === 0 || c.time <= more[i - 1].time)).toBe(true);
  });

  it('returns an empty report before data starts (E3)', () => {
    const r = usageReport({ from: '2026-06-01', to: '2026-06-07' });
    expect(r.empty).toBe(true);
    expect(r.totals.successRate).toBeNull();
    expect(r.change).toBeNull();
  });

  it('parses 8-digit dates, detects presets, and aggregates long ranges by week', () => {
    expect(parseCompactDate('20260921')).toBe('2026-09-21');
    expect(parseCompactDate('20260231')).toBeUndefined();
    expect(detectPreset({ from: '2026-09-21', to: '2026-09-27' })).toBe('7d');
    expect(detectPreset({ from: '2026-09-01', to: '2026-09-10' })).toBe('custom');
    expect(presetRange('lastMonth')).toEqual({ from: '2026-08-01', to: '2026-08-31' });
    expect(usageReport({ from: '2026-07-01', to: '2026-09-27' }).granularity).toBe('week');
  });
});
