import { splitHighlight } from '@/services/search';

/** 关键词高亮：命中部分使用琥珀色（#b86e12），可选加粗 */
export function Highlight({ text, query, strong }: { text: string; query: string; strong?: boolean }) {
  return (
    <>
      {splitHighlight(text, query).map((p, i) =>
        p.hit ? (
          <mark key={i} className={strong ? 'bg-transparent font-medium text-[#b86e12]' : 'bg-transparent text-[#b86e12]'}>
            {p.text}
          </mark>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  );
}
