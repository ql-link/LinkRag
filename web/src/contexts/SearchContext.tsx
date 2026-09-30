import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

import { CommandPalette } from '@/components/search/CommandPalette';

interface SearchValue {
  /** 打开 ⌘K 快速搜索，可带初始关键词 */
  openPalette: (query?: string) => void;
}

const SearchContext = createContext<SearchValue>({ openPalette: () => {} });

/** 全局快速搜索：⌘K / Ctrl+K 在任意页面唤起（B4） */
export function SearchProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [initial, setInitial] = useState('');

  const openPalette = useCallback((query = '') => {
    setInitial(query);
    setOpen(true);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen((v) => {
          if (!v) setInitial('');
          return !v;
        });
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  return (
    <SearchContext.Provider value={{ openPalette }}>
      {children}
      {open && <CommandPalette initialQuery={initial} onClose={() => setOpen(false)} />}
    </SearchContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export const useSearch = () => useContext(SearchContext);
