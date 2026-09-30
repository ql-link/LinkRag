import { useState } from 'react';
import { Link } from 'react-router-dom';

import logo from '@/assets/brand/logo-mark.png';
import { cn } from '@/lib/cn';

import { Benchmarks } from './Benchmarks';
import { DemoTabs } from './DemoTabs';
import HeroDemo from './HeroDemo';
import { pill, Reveal, SectionHead, TypeTag } from './shared';
import { PublicShell, useEntry } from './SiteChrome';

/**
 * 公开落地页（设计稿「06 落地页」L1 桌面 / L4 移动端 390）。
 * 未登录访问 / 时展示；已登录直接进入工作台首页（见 App 路由）。
 */
export default function LandingPage() {
  return (
    <PublicShell>
      <Hero />
      <DemoTabs />
      <Benchmarks />
      <WhyLinkRag />
      <Evidence />
      <Steps />
      <FinalCta />
    </PublicShell>
  );
}

function Hero() {
  const { authed, start } = useEntry();
  return (
    <section aria-labelledby="hero-title" className="flex flex-col items-center px-5 pt-14 pb-20 md:px-[100px] md:pt-[88px] md:pb-[120px]">
      <h1 id="hero-title" style={{ animationDelay: '0ms' }} className="animate-land-rise text-center font-serif text-[clamp(44px,6.8vw,76px)] leading-[1.16] font-semibold tracking-[-0.02em]">
        让知识
        <br className="sm:hidden" />
        可问可答
      </h1>
      <p style={{ animationDelay: '160ms' }} className="mt-5 max-w-[660px] animate-land-rise text-center text-[16px] leading-[28px] text-text2 md:text-[18px] md:leading-[30px]">
        上传文档，自动构建知识库。围绕内容直接提问，答案溯源至原文<span className="sm:hidden">。</span>
        <span className="hidden sm:inline">
          ，
          <br className="hidden md:block" />
          使每一份资料都被检索、被理解、被使用。
        </span>
      </p>
      <div style={{ animationDelay: '240ms' }} className="mt-6 flex w-full animate-land-rise flex-col gap-2.5 sm:mt-9 sm:w-auto sm:flex-row sm:gap-3">
        <Link to={start} className={cn(pill.primary, 'px-[26px] py-[13px] text-[15px]')}>
          {authed ? '进入工作台' : '免费开始使用'}
        </Link>
        <a href="#demo" className={cn(pill.secondary, 'px-6 py-[13px] text-[15px]')}>
          观看演示
        </a>
      </div>
      <p style={{ animationDelay: '320ms' }} className="mt-3.5 hidden animate-land-rise text-center text-[12.5px] text-muted sm:block">
        支持 PDF · DOCX · MD · XLSX　·　开源，可私有化部署
      </p>
      <div className="mt-7 w-full md:mt-16">
        <HeroDemo />
      </div>
    </section>
  );
}

/* ---------------- 为什么选择 LinkRag ---------------- */

const visual = 'relative h-[220px] overflow-hidden rounded-[14px] bg-gradient-to-b from-[#f6f1e9] to-soft';
const mini = 'absolute top-9 left-1/2 flex w-[min(300px,calc(100%-48px))] -translate-x-1/2 flex-col rounded-xl border border-divider bg-white shadow-[0_6px_18px_0_rgba(28,26,20,0.07)]';

function Toggle({ on }: { on: boolean }) {
  return (
    <span aria-hidden className={cn('relative h-4 w-7 rounded-full', on ? 'bg-brand' : 'bg-line')}>
      <span className={cn('absolute top-0.5 size-3 rounded-full bg-white', on ? 'right-0.5' : 'left-0.5')} />
    </span>
  );
}

const BARS = [28, 40, 34, 52, 46, 60, 38, 56, 64, 48, 58, 70];

function WhyCard({ title, desc, short, dot, children }: { title: string; desc: string; short: string; dot: string; children: React.ReactNode }) {
  return (
    <article className="flex items-center gap-3.5 rounded-2xl border border-divider bg-[#fbfbf9] p-[15px] md:block md:overflow-hidden md:rounded-[20px] md:p-0">
      {/* 窄屏（设计稿 L4）：图标 + 标题 + 一句话 */}
      <span aria-hidden className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-[#f6f1e9] md:hidden">
        <span style={{ background: dot }} className="size-2.5 rounded-full" />
      </span>
      <div className="flex flex-col gap-1 md:hidden">
        <h3 className="text-[14.5px] font-medium text-ink">{title}</h3>
        <p className="text-[12.5px] text-muted">{short}</p>
      </div>
      <div className="hidden md:flex md:flex-col">
      <div className="px-2 pt-2">
        <div aria-hidden className={visual}>
          {children}
        </div>
      </div>
      <div className="flex flex-col gap-2 px-6 pt-5 pb-[26px]">
        <h3 className="text-[18px] font-medium text-ink">{title}</h3>
        <p className="text-[14px] leading-[23px] text-text2">{desc}</p>
      </div>
      </div>
    </article>
  );
}

function WhyLinkRag() {
  return (
    <section id="features" aria-labelledby="why-title" className="scroll-mt-16 border-y border-divider bg-white px-4 py-12 md:px-[100px] md:py-[120px]">
      <Reveal className="mx-auto flex max-w-[1240px] flex-col items-center">
        <SectionHead id="why-title" eyebrow="为什么选择 LinkRag" title="为可信的检索问答而设计" />
        <div className="mt-8 grid w-full gap-2.5 md:mt-14 md:grid-cols-3 md:gap-6">
          <WhyCard short="填写密钥即可接入" dot="#7b8fa8" title="多家模型，随时切换" desc="接入常用模型厂商，填写密钥即可使用；对话中按需切换默认模型。">
            <div className={cn(mini, 'gap-2 p-3')}>
              <span className="text-[12.5px] font-medium text-ink">模型配置</span>
              {[
                ['DeepSeek', '#7b8fa8', true],
                ['通义千问', '#c8925a', true],
                ['Kimi', '#7d9a7e', false],
              ].map(([n, c, on]) => (
                <span key={n as string} className="flex items-center gap-2">
                  <span style={{ background: c as string }} className="size-[7px] rounded-full" />
                  <span className="text-[12px] text-ink">{n}</span>
                  <span className="flex-1" />
                  <Toggle on={on as boolean} />
                </span>
              ))}
            </div>
          </WhyCard>
          <WhyCard short="按模型与知识库统计" dot="#c8925a" title="用量清晰可查" desc="按模型与知识库统计 token 与调用次数，成本一目了然。">
            <div className={cn(mini, 'gap-3 p-3')}>
              <span className="flex items-center">
                <span className="text-[12px] font-medium text-ink">本月 Token</span>
                <span className="flex-1" />
                <span className="font-num text-[13px] font-semibold text-ink">1.28M</span>
              </span>
              <span className="flex h-[70px] items-end justify-between">
                {BARS.map((h, i) => (
                  <span key={i} style={{ height: h }} className={cn('w-4 rounded-[4px]', i === 10 ? 'bg-[#c8925a]' : 'bg-ink/14')} />
                ))}
              </span>
              <span className="flex items-center">
                <span className="text-[12px] text-ink">较上月</span>
                <span className="flex-1" />
                <span className="font-num text-[11px] font-medium text-[#5b7a5c]">↓ 12%</span>
              </span>
            </div>
          </WhyCard>
          <WhyCard short="数据留在你的服务器" dot="#7d9a7e" title="开源，可私有化部署" desc="代码开源，数据留在你自己的服务器；向量与关键词索引均可重建。">
            <div className={cn(mini, 'top-10 gap-1.5 p-3.5 font-mono text-[11px] leading-[18px]')}>
              <span className="mb-0.5 flex gap-1.5">
                {[0, 1, 2].map((i) => (
                  <span key={i} className="size-2 rounded-full bg-line" />
                ))}
              </span>
              <span className="truncate text-ink">
                <span className="text-muted">$ </span>git clone github.com/ql-link/linkrag
              </span>
              <span className="text-ink">
                <span className="text-muted">$ </span>docker compose up -d
              </span>
              <span className="truncate text-[#5b7a5c]">
                <span className="text-muted">✓ </span>mysql · qdrant · manticore 已就绪
              </span>
              <span className="text-[#5b7a5c]">
                <span className="text-muted">✓ </span>LinkRag 运行于 :8080
              </span>
            </div>
          </WhyCard>
        </div>
      </Reveal>
    </section>
  );
}

/* ---------------- 证据优先 ---------------- */

const EVIDENCE = [
  { type: 'PDF', name: '产品规划.pdf', page: '第 3 页', text: '围绕用户核心场景，提供可验证的解决方案。' },
  { type: 'DOCX', name: '技术说明.docx', page: '第 1 页', text: '检索增强生成结合可追溯来源，为每个结论提供可靠依据。' },
  { type: 'MD', name: '上线方案.md', page: '第 2 页', text: '通过增量同步与版本记录协调产品目标与技术实现。' },
];

function Evidence() {
  const [active, setActive] = useState(1);
  return (
    <section aria-labelledby="evidence-title" className="px-4 py-12 md:px-[100px] md:py-[120px]">
      <Reveal className="mx-auto flex max-w-[1040px] flex-col items-center">
        <SectionHead id="evidence-title" eyebrow="证据优先" title="答案不是终点，证据才是" desc="把分散的资料沉淀为可验证的知识链路。每个结论都能回到来源，每次追问都有上下文可循。" />
        <div className="mt-8 flex md:mt-14 w-full flex-col overflow-hidden rounded-[24px] border border-divider bg-white shadow-[0_20px_50px_0_rgba(28,26,20,0.07)] md:flex-row">
          <div className="flex flex-1 flex-col gap-3.5 p-7 md:p-10">
            <p className="flex items-center gap-2">
              <span aria-hidden className="size-2 rounded-full bg-[#c8925a]" />
              <span className="text-[13px] font-medium text-ink">最终结论</span>
              <span className="text-[12px] text-muted">基于 3 个来源 · 3 处引用</span>
            </p>
            <p className="mt-1.5 font-serif text-[22px] leading-[38px] font-semibold text-ink md:text-[24px] md:leading-[40px]">
              产品目标与技术约束之间的冲突，可以通过
              {['分阶段优化', '增量同步', '版本协同'].map((t, i) => (
                <span key={t}>
                  {i > 0 && (i === 2 ? '与' : '、')}
                  <button
                    type="button"
                    onMouseEnter={() => setActive(i)}
                    onFocus={() => setActive(i)}
                    onClick={() => setActive(i)}
                    aria-label={`${t}，查看引用 ${i + 1}`}
                    className={cn('rounded-[4px] px-0.5 underline decoration-[#c8925a]/50 decoration-2 underline-offset-[6px] transition-colors', active === i && 'bg-[#f6f1e9] decoration-[#c8925a]')}
                  >
                    {t}
                  </button>
                </span>
              ))}
              来化解。
            </p>
            <p className="mt-1.5 max-w-[420px] text-[13.5px] leading-[22px] text-text2">每一句结论都标注来源，点击即可跳转到原文所在页。</p>
          </div>
          <div className="flex flex-col gap-2.5 bg-[#f6f1e9] p-6 md:w-[500px] md:p-7">
            <p className="text-[12px] font-medium text-[#a8733f]">来源证据</p>
            {EVIDENCE.map((e, i) => (
              <div
                key={e.name}
                onMouseEnter={() => setActive(i)}
                className={cn(active !== i && 'hidden md:flex', 'flex flex-col gap-1.5 rounded-[14px] border bg-white p-3.5 transition-[border-color,box-shadow] duration-200', active === i ? 'border-[#c8925a]/60 shadow-[0_4px_12px_0_rgba(28,26,20,0.06)]' : 'border-divider')}
              >
                <div className="flex items-center gap-2">
                  <TypeTag type={e.type} />
                  <span className="text-[12.5px] font-medium text-ink">{e.name}</span>
                  <span className="text-[11px] text-muted">{e.page}</span>
                  <span className="flex-1" />
                  <span className={cn('rounded-[4px] px-1.5 py-px text-[10px] transition-colors', active === i ? 'bg-[#c8925a] text-white' : 'bg-soft text-text2')}>引用 {i + 1}</span>
                </div>
                <p className="text-[12.5px] leading-5 text-text2">{e.text}</p>
              </div>
            ))}
          </div>
        </div>
      </Reveal>
    </section>
  );
}

/* ---------------- 快速上手 ---------------- */

const STEPS = [
  ['创建知识库', '命名并选择向量模型，几秒完成'],
  ['上传文件', '拖入 PDF、DOCX、MD、XLSX，自动解析'],
  ['配置模型', '接入常用厂商，填写密钥即可'],
  ['开始提问', '在对话中选择知识库，答案附带引用'],
];

function Steps() {
  return (
    <section aria-labelledby="steps-title" className="hidden border-t border-divider bg-white px-5 py-20 sm:block md:px-[100px] md:py-28">
      <Reveal className="mx-auto flex max-w-[1240px] flex-col items-center">
        <SectionHead id="steps-title" eyebrow="快速上手" title="四步，开始你的第一个知识库" />
        <ol className="mt-14 grid w-full gap-8 sm:grid-cols-2 lg:grid-cols-4 lg:gap-0">
          {STEPS.map(([t, d], i) => (
            <li key={t} className={cn('flex flex-col gap-3', i > 0 && 'lg:border-l lg:border-divider lg:pl-7', i < 3 && 'lg:pr-7')}>
              <span className={cn('flex size-8 items-center justify-center rounded-full font-num text-[13px] font-semibold', i === 3 ? 'bg-brand text-white' : 'bg-soft text-ink')}>{i + 1}</span>
              <h3 className="mt-1 text-[17px] font-medium text-ink">{t}</h3>
              <p className="text-[13.5px] leading-[22px] text-text2">{d}</p>
            </li>
          ))}
        </ol>
      </Reveal>
    </section>
  );
}

/* ---------------- 结尾 CTA / 页脚 ---------------- */

function FinalCta() {
  const { authed, start } = useEntry();
  return (
    <section aria-labelledby="cta-title" className="bg-white px-5 pt-10 pb-20 md:px-[100px] md:pb-[120px]">
      <Reveal className="mx-auto flex max-w-[1240px] flex-col items-center rounded-[28px] bg-gradient-to-r from-[#f3e9dc] to-[#eef0ea] px-6 py-16 text-center md:px-10 md:py-[88px]">
        <img src={logo} alt="" width={52} height={52} className="object-contain" />
        <h2 id="cta-title" className="mt-6 font-serif text-[clamp(28px,3.9vw,42px)] leading-[1.29] font-semibold text-ink">
          现在就把资料变成可问的知识
        </h2>
        <p className="mt-3.5 text-[16px] text-text2">开源、可私有化部署。创建知识空间只需一分钟。</p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <Link to={authed ? '/datasets' : start} className={cn(pill.primary, 'px-[26px] py-[13px] text-[15px]')}>
            创建知识空间
          </Link>
          {!authed && (
            <Link to="/login" className={cn(pill.secondary, 'px-[26px] py-[13px] text-[15px]')}>
              登录 LinkRag
            </Link>
          )}
        </div>
      </Reveal>
    </section>
  );
}
