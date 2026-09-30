/**
 * 界面整体缩放：设计稿以 1392 宽为基准，在 1920 等宽屏上侧栏、按钮与文字会显得偏小。
 * 按视口尺寸计算 --ui-scale（1 ~ MAX），index.css 用它给 body 设置 CSS zoom，相当于浏览器缩放但随窗口自动计算；
 * 缩放后的"逻辑宽度"仍 ≥ 1392，内容区的流式布局照常生效。弹窗等通过 portal 挂在 body 下，一并缩放。
 */
const BASE_W = 1600;
const BASE_H = 900;
const MAX = 1.25;

export function computeUiScale(width: number, height: number): number {
  const s = Math.min(width / BASE_W, height / BASE_H, MAX);
  return Math.max(1, Math.round(s * 100) / 100);
}

export function installUiScale() {
  const apply = () => {
    const s = computeUiScale(window.innerWidth, window.innerHeight);
    document.documentElement.style.setProperty('--ui-scale', String(s));
  };
  apply();
  window.addEventListener('resize', apply);
  return () => window.removeEventListener('resize', apply);
}
