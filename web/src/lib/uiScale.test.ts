import { computeUiScale } from './uiScale';

describe('computeUiScale', () => {
  it('keeps design size on small screens and scales up on wide screens with a cap', () => {
    expect(computeUiScale(1392, 976)).toBe(1);
    expect(computeUiScale(1728, 1117)).toBe(1.08); // 16 寸 MacBook Pro
    expect(computeUiScale(1920, 1112)).toBe(1.2);
    expect(computeUiScale(2560, 1440)).toBe(1.25); // 27 寸 4K（2560 逻辑宽度），封顶
    expect(computeUiScale(2560, 800)).toBe(1); // 高度不足时不放大，避免纵向拥挤
  });
});
