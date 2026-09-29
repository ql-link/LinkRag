import { Link } from 'react-router-dom';

import { PageHeader } from '@/components/PageHeader';
import { PageColumn } from '@/layouts/AppLayout';

/** 分阶段交付占位页：首页、模型配置、用量、对话将在后续阶段按设计稿实现 */
export default function ComingSoonPage({ title }: { title: string }) {
  return (
    <PageColumn>
      <PageHeader eyebrow="LinkRag" title={title} description="该页面将在下一阶段按新设计稿实现。" />
      <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-dash py-16 text-[12.5px] text-muted">
        即将上线
        <Link to="/datasets" className="text-ink underline-offset-2 hover:underline">
          先去管理知识库
        </Link>
      </div>
    </PageColumn>
  );
}
