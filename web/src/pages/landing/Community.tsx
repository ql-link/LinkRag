import { Check, Copy } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';

import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';

import { QqIcon, QrIcon, WechatIcon } from './brandIcons';
import { COMMUNITY, DISCUSSIONS_URL } from './shared';

/**
 * 社群入口（设计稿 08 · Site/CommunityPopover）：
 * 桌面为顶栏按钮 + 弹层（点击打开，Esc / 点击外部 / 再次点击关闭，焦点移入弹层）；
 * 移动端菜单内改为按钮（复制微信号 / 一键加群），不展示二维码。
 */

type Channel = 'wechat' | 'qq';
const STORE_KEY = 'linkrag.community.channel';
const ext = { target: '_blank', rel: 'noreferrer noopener' } as const;

const channels = (): Channel[] => [...(COMMUNITY.wechatQr ? (['wechat'] as const) : []), ...(COMMUNITY.qqQr ? (['qq'] as const) : [])];

function useChannel(list: Channel[]) {
  const [channel, setChannel] = useState<Channel>(() => {
    const saved = localStorage.getItem(STORE_KEY) as Channel | null;
    return saved && list.includes(saved) ? saved : (list[0] ?? 'wechat');
  });
  const pick = (c: Channel) => {
    setChannel(c);
    localStorage.setItem(STORE_KEY, c);
  };
  return [channel, pick] as const;
}

export function CommunityButton() {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !root.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    panel.current?.focus();
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div ref={root} className="relative">
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className={cn('flex items-center gap-1.5 rounded-full px-3 py-[7px] text-[14px] transition-colors', open ? 'bg-[#f1f0ec] font-medium text-ink' : 'text-text2 hover:bg-[#f1f0ec] hover:text-ink')}
      >
        <QrIcon />
        社群
      </button>
      {open && (
        <div
          ref={panel}
          id={id}
          role="dialog"
          aria-label="加入 LinkRag 社群"
          tabIndex={-1}
          // 右缘对齐按钮右缘；按钮距视口右侧 ≥ 48，满足「右缘距视口 ≥ 24」
          className="absolute top-full right-0 z-40 mt-2.5 w-[334px] animate-rise-in outline-none"
        >
          <span aria-hidden className="absolute -top-1.5 right-7 size-3 rotate-45 border-t border-l border-divider bg-white" />
          <CommunityCard />
        </div>
      )}
    </div>
  );
}

/** 弹层卡片：头部 / 分段切换 + 二维码 */
function CommunityCard() {
  const list = channels();
  const [channel, pick] = useChannel(list);
  return (
    <div className="flex flex-col gap-4 rounded-[20px] border border-divider bg-white p-5 shadow-[0_2px_6px_0_rgba(28,26,20,0.05),0_18px_40px_-8px_rgba(28,26,20,0.12)]">
      <div className="flex flex-col gap-1">
        <p className="font-serif text-[17px] font-semibold text-ink">加入 LinkRag 社群</p>
        <p className="text-[12.5px] text-muted">版本更新、部署答疑和检索调优交流</p>
      </div>
      {list.length === 0 ? (
        <div className="flex flex-col items-center gap-1.5 rounded-2xl border border-dashed border-line bg-[#fbfbf9] px-4 py-9 text-center">
          <QrIcon size={28} className="text-faint" />
          <p className="mt-1 text-[14px] font-medium text-ink">社群即将开放</p>
          <p className="text-[12.5px] text-muted">先到 GitHub Discussions 交流</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3.5">
          {list.length > 1 && (
            <div role="tablist" aria-label="社群渠道" className="flex gap-0.5 rounded-full bg-[#f1f0ec] p-[3px]">
              {list.map((c) => {
                const on = c === channel;
                return (
                  <button
                    key={c}
                    type="button"
                    role="tab"
                    aria-selected={on}
                    onClick={() => pick(c)}
                    className={cn('flex flex-1 items-center justify-center gap-1.5 rounded-full py-[7px] text-[13px] transition-colors', on ? 'bg-white font-medium text-ink shadow-seg' : 'text-text2 hover:text-ink')}
                  >
                    {c === 'wechat' ? <WechatIcon className={on ? 'text-[#1aad19]' : 'text-muted'} /> : <QqIcon className={on ? 'text-[#1296db]' : 'text-muted'} />}
                    {c === 'wechat' ? '微信群' : 'QQ 群'}
                  </button>
                );
              })}
            </div>
          )}
          <QrBody channel={list.length > 1 ? channel : list[0]} />
        </div>
      )}
    </div>
  );
}

function QrBody({ channel }: { channel: Channel }) {
  const wechat = channel === 'wechat';
  const src = wechat ? COMMUNITY.wechatQr : COMMUNITY.qqQr;
  return (
    <div className="flex flex-col items-center gap-3.5">
      <div className="rounded-2xl border border-divider bg-white p-2.5">
        <img key={src} src={src} alt={wechat ? '微信群二维码' : 'QQ 群二维码'} width={176} height={176} className="size-[176px] animate-[fade-in_0.16s_ease-out] object-contain" />
      </div>
      <div className="flex flex-col items-center gap-1.5 text-center">
        <p className="text-[14px] font-medium text-ink">{wechat ? '微信扫码，加入群聊' : 'QQ 扫码，申请入群'}</p>
        <p className="text-[12.5px] text-muted">{wechat ? '二维码失效时可到 Discussions 留言' : '扫码后申请加入，管理员会尽快通过'}</p>
      </div>
    </div>
  );
}

/** 移动端菜单内的社群卡：手机无法扫描自身屏幕，改为复制微信号 / 一键加群；都未配置时打开二维码图片长按识别 */
export function CommunityMobile() {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const { wechatId, qqJoinUrl } = COMMUNITY;
  const copyId = async () => {
    if (!wechatId) return;
    try {
      await navigator.clipboard.writeText(wechatId);
    } catch {
      toast('复制失败，请手动添加微信号 ' + wechatId, { tone: 'error' });
      return;
    }
    setCopied(true);
    toast('已复制微信号，打开微信添加助手', { tone: 'success' });
    setTimeout(() => setCopied(false), 1600);
  };
  const tile = 'flex flex-1 flex-col items-start gap-0.5 rounded-[14px] bg-soft px-3.5 py-3 text-left';
  return (
    <div className="flex flex-col gap-3 rounded-[18px] border border-divider bg-white p-4">
      <p className="flex items-baseline justify-between">
        <span className="text-[15px] font-medium text-ink">加入社群</span>
        <span className="text-[12px] text-muted">版本更新 · 部署答疑</span>
      </p>
      {wechatId || qqJoinUrl ? (
        <div className="flex gap-2.5">
          {wechatId && (
            <button type="button" onClick={copyId} className={tile}>
              <span className="flex items-center gap-1.5 text-[13.5px] font-medium text-ink">
                <WechatIcon className="text-[#1aad19]" />
                微信群
              </span>
              <span className="flex items-center gap-1 text-[12px] text-muted">
                {copied ? <Check aria-hidden className="size-3" /> : <Copy aria-hidden className="size-3" />}
                复制助手微信号
              </span>
            </button>
          )}
          {qqJoinUrl && (
            <a href={qqJoinUrl} {...ext} className={tile}>
              <span className="flex items-center gap-1.5 text-[13.5px] font-medium text-ink">
                <QqIcon className="text-[#1296db]" />
                QQ 群
              </span>
              <span className="text-[12px] text-muted">一键加群 ↗</span>
            </a>
          )}
        </div>
      ) : COMMUNITY.wechatQr || COMMUNITY.qqQr ? (
        <div className="flex gap-2.5">
          {COMMUNITY.wechatQr && (
            <a href={COMMUNITY.wechatQr} {...ext} className={tile}>
              <span className="flex items-center gap-1.5 text-[13.5px] font-medium text-ink">
                <WechatIcon className="text-[#1aad19]" />
                微信群
              </span>
              <span className="text-[12px] text-muted">打开二维码，长按识别</span>
            </a>
          )}
          {COMMUNITY.qqQr && (
            <a href={COMMUNITY.qqQr} {...ext} className={tile}>
              <span className="flex items-center gap-1.5 text-[13.5px] font-medium text-ink">
                <QqIcon className="text-[#1296db]" />
                QQ 群
              </span>
              <span className="text-[12px] text-muted">打开二维码，长按识别</span>
            </a>
          )}
        </div>
      ) : (
        <a href={DISCUSSIONS_URL} {...ext} className="text-[13px] font-medium text-[#a8733f]">
          社群即将开放，先到 GitHub Discussions 交流 ↗
        </a>
      )}
    </div>
  );
}
