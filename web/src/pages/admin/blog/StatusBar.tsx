import type { Mode } from './EditorTopbar';

/** 底部状态栏：模式说明 · 字数与阅读时长 · 快捷提示 */
export function StatusBar({ mode, chars, cursor }: { mode: Mode; chars: number; cursor: { line: number; col: number } | null }) {
  const minutes = Math.max(1, Math.round(chars / 300));
  return (
    <div className="sticky bottom-0 z-10 flex h-8 items-center gap-4 border-t border-divider bg-white/95 px-5 text-[11px] text-muted backdrop-blur">
      <span>{mode === 'source' ? `源码模式 · Markdown${cursor ? ` · 第 ${cursor.line} 行，第 ${cursor.col} 列` : ''}` : '实时预览 · 点击段落显示 Markdown 源码，离开后渲染'}</span>
      <span className="font-num">
        {chars.toLocaleString('en-US')} 字 · 约 {minutes} 分钟阅读
      </span>
      <span className="ml-auto flex gap-4">
        <span>/ 插入块</span>
        <span>⌘⌥1–6 标题</span>
        <span>esc 完成编辑</span>
        <span>选中文字 → 格式工具栏</span>
        <span>⌘ / 源码模式</span>
        <span>⌘ S 保存</span>
      </span>
    </div>
  );
}
