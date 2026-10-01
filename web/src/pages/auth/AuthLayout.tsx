import { MessageSquare } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { Brand } from '@/components/brand/Brand';
import { DocCard } from '@/components/DocIllustration';
import { TypeTag } from '@/components/FileBadge';

/** 登录注册左侧品牌区的示意插画（Figma 10:514） */
function Artwork() {
  return (
    <div aria-hidden className="relative h-[330px] w-[508px] overflow-hidden rounded-[18px] border border-line bg-white p-1.5 shadow-[0_8px_24px_0_rgba(0,0,0,0.06)]">
      <div className="relative h-[316px] w-[494px] overflow-hidden rounded-xl bg-soft">
        <DocCard className="-rotate-6" style={{ left: 80, top: 56 }} />
        <TypeTag type="PDF" style={{ left: 130, top: 100 }} />
        <DocCard style={{ left: 136, top: 50 }} />
        <TypeTag type="MD" style={{ left: 190, top: 90 }} />
        <DocCard className="rotate-6" style={{ left: 192, top: 65 }} />
        <TypeTag type="DOCX" style={{ left: 250, top: 102 }} />
        <div className="absolute top-[168px] left-[250px] rounded-xl border border-line bg-white px-3 py-[9px] text-[12px] text-ink shadow-[0_4px_12px_0_rgba(0,0,0,0.06)]">
          Q3 路线图里优先级最高的是？
        </div>
        <div className="absolute top-[210px] left-10 flex flex-col gap-2 rounded-xl border border-line bg-white px-3.5 py-[11px] shadow-[0_6px_16px_0_rgba(0,0,0,0.08)]">
          <p className="text-[12px] text-ink">知识库多模态解析，10 月 15 日灰度上线。</p>
          <div className="flex gap-1.5">
            {['片段 1', '片段 3'].map((t) => (
              <span key={t} className="rounded-[5px] bg-blue/10 px-[7px] py-[3px] text-[10.5px] font-medium text-blue">
                {t}
              </span>
            ))}
          </div>
        </div>
        <div className="absolute top-[250px] left-[420px] flex size-9 items-center justify-center rounded-full bg-ink shadow-[0_4px_10px_0_rgba(0,0,0,0.12)]">
          <MessageSquare className="size-4 text-white" />
        </div>
      </div>
    </div>
  );
}

/** 登录 / 注册外壳：左侧品牌区（设计稿 620px，宽屏流式放宽至 760px）+ 右侧白色表单面板 */
export function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full min-h-[760px] bg-page">
      <section className="relative hidden w-[clamp(620px,40%,760px)] shrink-0 flex-col px-14 pt-12 pb-10 lg:flex">
        <Brand size={34} />
        <div className="mt-[98px] flex flex-col gap-3.5">
          <p className="text-[12px] text-muted">知识空间 · RAG 检索问答</p>
          <h2 className="font-serif text-[36px] leading-[52px] font-semibold text-ink">
            把你的资料，
            <br />
            变成可以对话的知识。
          </h2>
          <p className="text-[14px] text-text2">上传文档、配置解析，在对话中获得带引用来源的回答。</p>
        </div>
        <div className="mt-auto pt-10">
          <Artwork />
        </div>
        <p className="mt-auto pt-10 font-num text-[11px] font-medium text-faint">© 2026 LinkRag</p>
      </section>
      <section className="relative my-3 mr-3 ml-3 flex flex-1 flex-col rounded-2xl border border-line bg-white">
        <Link to="/home" className="absolute top-[31px] left-[39px] text-[12px] text-text2 hover:text-ink">
          返回首页
        </Link>
        <div className="flex flex-1 items-center justify-center py-20">
          <div className="w-[clamp(360px,21vw,400px)]">{children}</div>
        </div>
      </section>
    </div>
  );
}
