import { useEffect } from 'react';

/** ⌘S 保存、⌘/ 切换源码模式；有未保存修改时离开页面前提示 */
export function useEditorShortcuts({ dirty, onSave, onToggleMode }: { dirty: boolean; onSave: () => void; onToggleMode: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key.toLowerCase() === 's') {
        e.preventDefault();
        onSave();
      } else if (e.key === '/') {
        e.preventDefault();
        onToggleMode();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onSave, onToggleMode]);

  useEffect(() => {
    if (!dirty) return;
    const onUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  }, [dirty]);
}
