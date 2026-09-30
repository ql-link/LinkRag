import { describe, expect, it } from 'vitest';

import { bytes, growth } from './api';
import { compact, relTime } from './ui';

describe('管理台格式化', () => {
  const now = new Date('2026-09-30T15:00:00');
  it('相对时间', () => {
    expect(relTime('2026-09-30T14:31:00', now)).toBe('今天 14:31');
    expect(relTime('2026-09-29T22:14:00', now)).toBe('昨天 22:14');
    expect(relTime('2026-09-26T10:02:00', now)).toBe('09-26 10:02');
    expect(relTime('2025-11-02T08:00:00', now)).toBe('2025-11-02');
    expect(relTime(null, now)).toBe('—');
  });
  it('大数与字节', () => {
    expect(compact(1_280_000)).toBe('1.28M');
    expect(compact(2_000_000)).toBe('2M');
    expect(compact(86_000)).toBe('86K');
    expect(compact(0)).toBe('0');
    expect(bytes(612 * 1024 ** 2)).toBe('612 MB');
    expect(bytes(1.8 * 1024 ** 3)).toBe('1.8 GB');
  });
  it('环比', () => {
    expect(growth({ current: 842, previous: 749, growthRate: 0.124 })).toEqual({ text: '↑ 12.4%', up: true });
    expect(growth({ current: 3217, previous: 3323, growthRate: -0.032 })).toEqual({ text: '↓ 3.2%', up: false });
    expect(growth({ current: 1, previous: 0, growthRate: null })).toBeNull();
  });
});

describe('登录记录展示', async () => {
  const { device, maskIp } = await import('./api');
  it('设备识别', () => {
    expect(device('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/129.0.0.0 Safari/537.36')).toBe('Chrome 129 · macOS');
    expect(device('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1')).toBe('Safari · iOS 18');
    expect(device('Mozilla/5.0 (Windows NT 10.0) Chrome/129.0 Safari/537.36 Edg/129.0')).toBe('Edge 129 · Windows');
    expect(device(null)).toBe('未知设备');
  });
  it('IP 脱敏', () => {
    expect(maskIp('116.228.10.2')).toBe('116.228.**.**');
    expect(maskIp(null)).toBe('—');
  });
});
