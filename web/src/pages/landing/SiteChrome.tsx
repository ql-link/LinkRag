import { Menu, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

import logo from '@/assets/brand/logo-mark.png';
import { useAuth } from '@/contexts/AuthContext';
import { cn } from '@/lib/cn';

import { GithubIcon } from './brandIcons';
import { CommunityButton, CommunityMobile } from './Community';
import { BEIAN_URL, BLOG_URL, FEEDBACK_URL, GITHUB_URL } from './shared';

/** 公开页（落地页 / 研究与评测 / 博客 / 反馈）共用的顶栏、页脚与滚动容器 */

/** 工作台在大屏上会整体放大（lib/uiScale），公开页保持设计稿 1:1，离开时恢复 */
export function useNoUiScale() {
  useEffect(() => {
    document.documentElement.classList.add('no-ui-scale');
    return () => document.documentElement.classList.remove('no-ui-scale');
  }, []);
}

export const SCROLL_ROOT_ID = 'landing-scroll';

/** 公开页外壳：独立滚动容器 + 顶栏 + 页脚；切换路由时回到顶部 */
export function PublicShell({ children, className }: { children: React.ReactNode; className?: string }) {
  useNoUiScale();
  const { pathname, hash } = useLocation();
  useEffect(() => {
    const root = document.getElementById(SCROLL_ROOT_ID);
    if (!root) return;
    // 带锚点（如从其他页回到 /#features）时滚到对应区块，否则回到顶部
    const target = hash ? document.getElementById(decodeURIComponent(hash.slice(1))) : null;
    if (target) target.scrollIntoView();
    else root.scrollTop = 0;
  }, [pathname, hash]);
  return (
    // 纵向 flex + main 撑满：内容不足一屏时页脚仍贴底
    <div id={SCROLL_ROOT_ID} className={cn('relative flex h-full flex-col overflow-y-auto text-ink [scroll-behavior:smooth]', className ?? 'bg-[#fbfbf9]')}>
      <Nav />
      <main className="flex-1">{children}</main>
      <Footer />
    </div>
  );
}

/** 顶栏导航：首页回到落地页顶部，其余为站内页面 */
const LINKS = [
  { label: '首页', to: '/', match: (p: string) => p === '/' },
  { label: '评测', to: '/research', match: (p: string) => p.startsWith('/research') },
  { label: '博客', to: BLOG_URL, match: (p: string) => p.startsWith('/blog') },
  { label: '反馈', to: FEEDBACK_URL, match: (p: string) => p.startsWith('/feedback') },
];

const ext = { target: '_blank', rel: 'noreferrer noopener' } as const;

/** 顶栏主按钮：去掉落地页大按钮的投影，避免在细窄的顶栏里显得过重 */
const navPrimary = 'inline-flex items-center justify-center rounded-full bg-brand font-medium text-white transition-colors hover:bg-brand-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand';

/** 已登录时入口改为进入工作台；落地页的「开始使用」面向新访客，直达注册 */
export function useEntry() {
  const { user } = useAuth();
  return { authed: !!user, start: user ? '/home' : '/register' };
}

export function Brand({ size = 28, text = 'text-[17px]' }: { size?: number; text?: string }) {
  return (
    <span className="flex items-center gap-2.5">
      <img src={logo} alt="" width={size} height={size} className="object-contain" />
      <span className={cn('font-num font-semibold tracking-[-0.02em] text-ink', text)}>LinkRag</span>
    </span>
  );
}

function GithubButton({ className }: { className?: string }) {
  return (
    <a href={GITHUB_URL} {...ext} aria-label="GitHub 仓库（新标签打开）" className={cn('flex items-center justify-center gap-1.5 rounded-full px-3 py-[7px] text-[14px] text-text2 transition-colors hover:bg-[#f1f0ec] hover:text-ink', className)}>
      <GithubIcon />
      GitHub
    </a>
  );
}

function Nav() {
  const { authed } = useEntry();
  // 顶栏只保留一个入口：未登录进登录页（页内可切换到注册），已登录进工作台
  const entry = authed ? '/home' : '/login';
  const { pathname } = useLocation();
  const current = LINKS.find((l) => l.match(pathname));
  // 已在落地页时点「首页」/ 品牌：路由不变，手动回到顶部
  const toTop = (to: string) => () => {
    if (to === '/' && pathname === '/') document.getElementById(SCROLL_ROOT_ID)?.scrollTo({ top: 0 });
  };
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const root = document.getElementById(SCROLL_ROOT_ID);
    if (!root) return;
    const on = () => setScrolled(root.scrollTop > 8);
    root.addEventListener('scroll', on, { passive: true });
    return () => root.removeEventListener('scroll', on);
  }, []);
  useEffect(() => setOpen(false), [pathname]);
  return (
    <header className={cn('sticky top-0 z-30 transition-[background-color,box-shadow] duration-200', scrolled || open ? 'bg-[#fbfbf9]/85 shadow-[0_1px_0_0_#ececea] backdrop-blur-md' : 'bg-transparent')}>
      {/* 三栏：品牌 / 居中导航 / 右侧操作；两侧等宽，导航不随右侧按钮宽度偏移 */}
      <nav aria-label="主导航" className="flex h-[60px] items-center px-4 md:grid md:h-[72px] md:grid-cols-[1fr_auto_1fr] md:px-12">
        <Link to="/" onClick={toTop('/')} aria-label="LinkRag 首页" className="justify-self-start">
          <Brand />
        </Link>
        <span className="flex-1 md:hidden" />
        <ul className="hidden items-center gap-8 md:flex">
          {LINKS.map((l) => {
            const on = l === current;
            return (
              <li key={l.label}>
                <Link to={l.to} onClick={toTop(l.to)} aria-current={on ? 'page' : undefined} className={cn('flex flex-col items-center gap-[5px] pt-[7px] text-[14px] transition-colors', on ? 'font-medium text-ink' : 'text-text2 hover:text-ink')}>
                  {l.label}
                  <span aria-hidden className={cn('h-0.5 w-4 rounded-[1px] bg-brand', !on && 'invisible')} />
                </Link>
              </li>
            );
          })}
        </ul>
        <div className="flex items-center gap-1.5 justify-self-end">
          <GithubButton className="hidden md:flex" />
          <span className="hidden md:block">
            <CommunityButton />
          </span>
          <span aria-hidden className="mx-2 hidden h-4 w-px bg-line md:block" />
          <Link to={entry} className={cn(navPrimary, 'h-8 px-3.5 text-[13px] md:h-9 md:px-4 md:text-[14px]')}>
            {authed ? '进入工作台' : '开始使用'}
          </Link>
          <button type="button" aria-label={open ? '关闭菜单' : '打开菜单'} aria-expanded={open} onClick={() => setOpen((v) => !v)} className={cn('flex size-9 items-center justify-center rounded-full text-ink md:hidden', open && 'bg-[#f1f0ec]')}>
            {open ? <X className="size-4" /> : <Menu className="size-4" />}
          </button>
        </div>
      </nav>
      {open && (
        <div className="flex max-h-[calc(100dvh-60px)] flex-col gap-6 overflow-y-auto border-t border-divider bg-[#fbfbf9] px-6 pt-2 pb-7 md:hidden">
          <ul className="flex flex-col">
            {LINKS.map((l) => {
              const on = l === current;
              return (
                <li key={l.label} className="border-b border-divider last:border-b-0">
                  <Link to={l.to} onClick={() => (setOpen(false), toTop(l.to)())} aria-current={on ? 'page' : undefined} className={cn('flex items-center justify-between px-1 py-3.5 text-[17px]', on ? 'font-medium text-ink' : 'text-text2')}>
                    {l.label}
                    <span aria-hidden className="text-[14px] text-faint">
                      →
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
          <CommunityMobile />
          <GithubButton className="border border-line bg-white py-[9px] font-medium text-ink hover:bg-[#fbfbf9]" />
        </div>
      )}
    </header>
  );
}

export function Footer() {
  return (
    <footer className="flex flex-wrap items-center gap-x-7 gap-y-3 border-t border-divider bg-white px-5 pt-7 pb-9 text-[12.5px] text-muted md:px-[100px]">
      <span className="flex items-center gap-2">
        <img src={logo} alt="" width={20} height={20} className="object-contain" />
        <span className="font-num">© 2026 LinkRag</span>
      </span>
      <span className="hidden flex-1 md:block" />
      <Link to={BLOG_URL} className="hover:text-ink">
        博客
      </Link>
      <Link to={FEEDBACK_URL} className="hover:text-ink">
        反馈
      </Link>
      <a href={GITHUB_URL} {...ext} className="hover:text-ink">
        GitHub
      </a>
      <a href={BEIAN_URL} {...ext} className="hover:text-ink">
        皖ICP备2026017322号
      </a>
    </footer>
  );
}
