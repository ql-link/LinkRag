/** 日志分页（设计稿 E1 Pager）：后端最多拉取 1000 行，总页数未知时只提供上一页 / 下一页 */
import { cn } from '@/lib/cn';

import { FilterSelect } from './FilterSelect';
import { pageInfo } from './logic';

export const PAGE_SIZES = [20, 50, 100, 200];

export function Pager({ page, pageSize, total, shown, onPage, onPageSize }: { page: number; pageSize: number; total: number; shown: number; onPage: (p: number) => void; onPageSize: (n: number) => void }) {
  const info = pageInfo(total, page, pageSize);
  const btn = 'h-[26px] rounded-[6px] border border-line bg-white px-2.5 text-[11.5px] text-text2 transition-colors hover:bg-soft disabled:opacity-40 disabled:hover:bg-white';
  return (
    <nav aria-label="分页" className="flex flex-wrap items-center gap-3 pt-4">
      <span className="font-num text-[11.5px] text-muted">
        第 {page} 页，{info.exact ? `共 ${info.knownPages} 页` : '更多结果需翻页加载'} · 当前显示 {shown} 条
      </span>
      {info.capped && <span className="text-[11.5px] text-amber">结果超过 1,000 条，仅可浏览前 1,000 条，请缩小时间范围或增加筛选条件。</span>}
      <span className="ml-auto flex items-center gap-2">
        <span className="text-[11.5px] text-muted">每页</span>
        <FilterSelect
          label="每页条数"
          className="w-[72px] [&>span:first-child]:sr-only"
          width={80}
          num
          value={String(pageSize)}
          options={PAGE_SIZES.map((n) => ({ value: String(n), label: String(n) }))}
          onChange={(v) => onPageSize(Number(v))}
        />
        <button type="button" className={cn(btn)} disabled={!info.hasPrev} onClick={() => onPage(page - 1)}>
          上一页
        </button>
        <button type="button" className={cn(btn)} disabled={!info.hasNext} onClick={() => onPage(page + 1)}>
          下一页
        </button>
      </span>
    </nav>
  );
}
