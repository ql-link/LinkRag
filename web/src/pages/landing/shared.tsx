import { useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/cn';

/** 落地页公用：外链、Section 标题、类型标签、滚动出现 */

export const GITHUB_URL = (import.meta.env.VITE_GITHUB_URL as string | undefined)?.trim() || 'https://github.com/ql-link/LinkRag';
export const DISCUSSIONS_URL = `${GITHUB_URL}/discussions`;
export const ISSUES_URL = `${GITHUB_URL}/issues`;
/** 站内页面 */
export const BLOG_URL = '/blog';
export const FEEDBACK_URL = '/feedback';

const env = (v: string | undefined) => v?.trim() || undefined;

/**
 * 社群与联系方式：二维码默认取 public/community/ 下的图片，可用环境变量覆盖；
 * 微信号、QQ 一键加群链接和邮箱未配置时不展示对应入口。
 * 微信群二维码 7 天有效（当前一张到 10/7），过期后替换 public/community/wechat-qr.png。
 */
export const COMMUNITY = {
  wechatQr: env(import.meta.env.VITE_WECHAT_QR_URL) ?? '/community/wechat-qr.png',
  wechatId: env(import.meta.env.VITE_WECHAT_ID),
  qqQr: env(import.meta.env.VITE_QQ_QR_URL) ?? '/community/qq-qr.png',
  qqJoinUrl: env(import.meta.env.VITE_QQ_JOIN_URL),
  email: env(import.meta.env.VITE_CONTACT_EMAIL),
};
/** 安全问题：配置了安全邮箱时发邮件，否则走 GitHub 私密漏洞报告 */
export const SECURITY_EMAIL = env(import.meta.env.VITE_SECURITY_EMAIL);
export const SECURITY_URL = SECURITY_EMAIL ? `mailto:${SECURITY_EMAIL}` : `${GITHUB_URL}/security/advisories/new`;
export const BEIAN_URL = 'https://beian.miit.gov.cn/';

/** 元素进入视口（按比例阈值）后返回 true；once=true 时只触发一次 */
export function useInView<T extends Element>(threshold = 0.3, once = false) {
  const ref = useRef<T>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') return setInView(true);
    const obs = new IntersectionObserver(
      ([e]) => {
        setInView(e.isIntersecting);
        if (once && e.isIntersecting) obs.disconnect();
      },
      { threshold },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [threshold, once]);
  return [ref, inView] as const;
}

/** Section 滚动出现：opacity 0→1，y 24→0，仅播放一次 */
export function Reveal({ as: Tag = 'div', className, children, ...rest }: { as?: 'div' | 'section'; className?: string; children: React.ReactNode } & React.HTMLAttributes<HTMLElement>) {
  const [ref, shown] = useInView<HTMLDivElement>(0.12, true);
  return (
    <Tag ref={ref} className={cn('land-reveal', shown && 'land-revealed', className)} {...rest}>
      {children}
    </Tag>
  );
}

export function SectionHead({ id, eyebrow, title, desc, width = 600 }: { id?: string; eyebrow: string; title: string; desc?: string; width?: number }) {
  return (
    <div className="flex flex-col items-center text-center">
      <p className="text-[13px] font-medium text-[#a8733f]">{eyebrow}</p>
      <h2 id={id} className="mt-3 font-serif text-[clamp(24px,4.2vw,44px)] leading-[1.27] font-semibold tracking-[-0.01em] text-ink">
        {title}
      </h2>
      {desc && (
        <p style={{ maxWidth: width }} className="mt-3.5 hidden text-[16.5px] leading-[27px] text-text2 sm:block">
          {desc}
        </p>
      )}
    </div>
  );
}

const TYPE_TONE: Record<string, string> = {
  PDF: 'bg-[#c86a5a]/12 text-[#c86a5a]',
  DOCX: 'bg-[#7b8fa8]/12 text-[#7b8fa8]',
  MD: 'bg-[#c8925a]/12 text-[#c8925a]',
  XLSX: 'bg-[#7d9a7e]/12 text-[#7d9a7e]',
};

export function TypeTag({ type }: { type: keyof typeof TYPE_TONE | string }) {
  return <span className={cn('shrink-0 rounded-[4px] px-1.5 py-0.5 font-num text-[9.5px] leading-none font-semibold', TYPE_TONE[type])}>{type}</span>;
}

/** 胶囊按钮：主按钮墨色实心，次按钮白底描边 */
export const pill = {
  primary:
    'inline-flex items-center justify-center rounded-full bg-brand font-medium text-white shadow-[0_1px_0_0_rgba(255,255,255,0.18)_inset,0_6px_16px_-6px_rgba(156,106,58,0.55)] transition-colors hover:bg-brand-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand',
  secondary: 'inline-flex items-center justify-center rounded-full border border-line bg-white font-medium text-ink transition-colors hover:border-dash hover:bg-[#fbfbf9]',
};

/** 公共页页头（博客 / 评测 / 反馈统一）：衬线大标题 + 说明，右侧可放操作区，下方可接补充内容 */
export function PageIntro({ title, desc, aside, children }: { title: string; desc: React.ReactNode; aside?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <header className="px-5 pt-10 pb-8 md:px-[100px] md:pt-14 md:pb-9">
      <div className="mx-auto w-full max-w-[1240px]">
        <div className="flex flex-col gap-6 md:flex-row md:items-end">
          <div className="flex max-w-[620px] flex-col gap-3.5">
            <h1 className="font-serif text-[clamp(32px,4.4vw,44px)] leading-tight font-semibold tracking-[-0.01em] text-ink">{title}</h1>
            <p className="text-[16px] leading-[27px] text-text2">{desc}</p>
          </div>
          {aside && (
            <>
              <span className="hidden flex-1 md:block" />
              {aside}
            </>
          )}
        </div>
        {children}
      </div>
    </header>
  );
}
