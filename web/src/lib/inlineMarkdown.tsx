/**
 * 行内 Markdown：`code`、**粗体**、*斜体* / _斜体_、~~删除线~~、[链接](url)、<https://自动链接>、![图片](url)、\ 转义。
 *
 * 解析结果无损（sourceOf(parseInline(s)) === s），供三处共用：
 * 官网正文渲染、后台编辑器的渲染态，以及编辑态源码的语法着色 / 点击位置到源码偏移的换算。
 */
import { Fragment, type ReactNode } from 'react';

export type INode =
  | { t: 'text'; v: string; raw: string }
  | { t: 'code'; v: string; open: string; close: string }
  | { t: 'img'; alt: string; src: string; raw: string }
  | { t: 'strong' | 'em' | 'del'; mark: string; children: INode[] }
  | { t: 'link'; href: string; open: string; close: string; children: INode[] };

const ESCAPABLE = /[\\`*_{}[\]()#+\-.!~|>]/;
const WORD = /[\p{L}\p{N}]/u;

const RE = {
  code: /(`+)([^`\n]|[^`\n][\s\S]*?[^`\n])\1(?!`)/y,
  img: /!\[([^\]\n]*)\]\(([^)\s]+)\)/y,
  link: /\[((?:\\.|[^\]\\\n])+)\]\(([^)\s]+)\)/y,
  auto: /<((?:https?:\/\/|mailto:)[^>\s]+)>/y,
  strong: /(\*\*|__)(?![\s*_])([\s\S]+?)(?<!\s)\1/y,
  del: /~~(?!\s)([\s\S]+?)(?<!\s)~~/y,
  emStar: /\*(?![\s*])((?:\\.|[^*\\\n])+?)(?<!\s)\*/y,
  emUnder: /_(?![\s_])((?:\\.|[^_\\\n])+?)(?<!\s)_/y,
};

function at(re: RegExp, src: string, i: number) {
  re.lastIndex = i;
  return re.exec(src);
}

export function parseInline(src: string): INode[] {
  const out: INode[] = [];
  let buf = '';
  const flush = () => {
    if (buf) out.push({ t: 'text', v: buf, raw: buf });
    buf = '';
  };
  const push = (n: INode, len: number) => {
    flush();
    out.push(n);
    return len;
  };
  let i = 0;
  while (i < src.length) {
    const ch = src[i];
    let m: RegExpExecArray | null = null;
    let step = 0;
    if (ch === '\\' && ESCAPABLE.test(src[i + 1] ?? '')) {
      step = push({ t: 'text', v: src[i + 1], raw: `\\${src[i + 1]}` }, 2);
    } else if (ch === '`' && (m = at(RE.code, src, i))) {
      step = push({ t: 'code', v: m[2], open: m[1], close: m[1] }, m[0].length);
    } else if (ch === '!' && (m = at(RE.img, src, i))) {
      step = push({ t: 'img', alt: m[1], src: m[2], raw: m[0] }, m[0].length);
    } else if (ch === '[' && (m = at(RE.link, src, i))) {
      step = push({ t: 'link', href: m[2], open: '[', close: `](${m[2]})`, children: parseInline(m[1]) }, m[0].length);
    } else if (ch === '<' && (m = at(RE.auto, src, i))) {
      step = push({ t: 'link', href: m[1], open: '<', close: '>', children: [{ t: 'text', v: m[1], raw: m[1] }] }, m[0].length);
    } else if ((ch === '*' || ch === '_') && src[i + 1] === ch && (m = at(RE.strong, src, i)) && (ch === '*' || !WORD.test(src[i - 1] ?? ''))) {
      step = push({ t: 'strong', mark: m[1], children: parseInline(m[2]) }, m[0].length);
    } else if (ch === '~' && (m = at(RE.del, src, i))) {
      step = push({ t: 'del', mark: '~~', children: parseInline(m[1]) }, m[0].length);
    } else if (ch === '*' && (m = at(RE.emStar, src, i))) {
      step = push({ t: 'em', mark: '*', children: parseInline(m[1]) }, m[0].length);
    } else if (ch === '_' && !WORD.test(src[i - 1] ?? '') && (m = at(RE.emUnder, src, i)) && !WORD.test(src[i + m[0].length] ?? '')) {
      step = push({ t: 'em', mark: '_', children: parseInline(m[1]) }, m[0].length);
    }
    if (step) i += step;
    else {
      buf += ch;
      i += 1;
    }
  }
  flush();
  return out;
}

/** 节点还原为源码（与输入逐字一致） */
export function sourceOf(nodes: INode[]): string {
  return nodes
    .map((n) => {
      switch (n.t) {
        case 'text':
        case 'img':
          return n.raw;
        case 'code':
          return n.open + n.v + n.close;
        case 'link':
          return n.open + sourceOf(n.children) + n.close;
        default:
          return n.mark + sourceOf(n.children) + n.mark;
      }
    })
    .join('');
}

/** 去掉标记后的可见文字（摘要、字数统计） */
export function plainInline(src: string): string {
  const walk = (ns: INode[]): string => ns.map((n) => (n.t === 'text' || n.t === 'code' ? n.v : n.t === 'img' ? '' : walk(n.children))).join('');
  return walk(parseInline(src));
}

/** 只放行常见协议与站内相对地址，避免 javascript: 等链接 */
export function safeHref(url: string): string | null {
  return /^(https?:|mailto:|\/(?!\/)|#|\.{1,2}\/)/i.test(url.trim()) ? url.trim() : null;
}
export function safeSrc(url: string): string | null {
  return /^(https?:|\/(?!\/)|blob:|data:image\/)/i.test(url.trim()) ? url.trim() : null;
}

const codeCls = 'rounded-[5px] bg-soft px-1.5 py-0.5 font-mono text-[0.88em] text-ink';

function render(nodes: INode[], key = ''): ReactNode[] {
  return nodes.map((n, i) => {
    const k = `${key}${i}`;
    switch (n.t) {
      case 'text':
        return <Fragment key={k}>{n.v}</Fragment>;
      case 'code':
        return (
          <code key={k} className={codeCls}>
            {n.v}
          </code>
        );
      case 'img': {
        const src = safeSrc(n.src);
        return src ? <img key={k} src={src} alt={n.alt} className="inline-block max-h-[1.6em] align-text-bottom" /> : <Fragment key={k}>{n.raw}</Fragment>;
      }
      case 'strong':
        return (
          <strong key={k} className="font-semibold text-ink">
            {render(n.children, `${k}.`)}
          </strong>
        );
      case 'em':
        return <em key={k}>{render(n.children, `${k}.`)}</em>;
      case 'del':
        return (
          <del key={k} className="text-muted">
            {render(n.children, `${k}.`)}
          </del>
        );
      case 'link': {
        const href = safeHref(n.href);
        if (!href) return <Fragment key={k}>{render(n.children, `${k}.`)}</Fragment>;
        const external = /^(https?:|mailto:)/i.test(href);
        return (
          <a key={k} href={href} {...(external ? { target: '_blank', rel: 'noreferrer' } : {})} className="text-brand underline decoration-brand/40 underline-offset-[3px] hover:decoration-brand">
            {render(n.children, `${k}.`)}
          </a>
        );
      }
    }
  });
}

/** 渲染行内 Markdown */
export function Inline({ text }: { text: string }) {
  return <>{render(parseInline(text))}</>;
}

/** 编辑态源码着色：语法标记置灰，文字保持原色（不改字重，保证与文本域逐字对齐） */
export function highlightInline(src: string): ReactNode[] {
  const mark = (s: string, k: string) => (
    <span key={k} className="text-faint">
      {s}
    </span>
  );
  const walk = (ns: INode[], key: string): ReactNode[] =>
    ns.flatMap((n, i) => {
      const k = `${key}${i}`;
      switch (n.t) {
        case 'text':
          return n.raw.length > n.v.length ? [mark('\\', `${k}e`), n.v] : [n.raw];
        case 'img':
          return [mark(n.raw, k)];
        case 'code':
          return [mark(n.open, `${k}o`), <span key={`${k}v`} className="text-ink">{n.v}</span>, mark(n.close, `${k}c`)];
        case 'link':
          return [mark(n.open, `${k}o`), <span key={`${k}v`} className="text-brand">{walk(n.children, `${k}.`)}</span>, mark(n.close, `${k}c`)];
        default:
          return [mark(n.mark, `${k}o`), <span key={`${k}v`} className="text-ink">{walk(n.children, `${k}.`)}</span>, mark(n.mark, `${k}c`)];
      }
    });
  return walk(parseInline(src), '');
}

/** 渲染态中第 visible 个可见字符 → 源码偏移（用于点击后把光标放到对应位置） */
export function rawOffsetOf(src: string, visible: number): number {
  let v = 0;
  let r = 0;
  const go = (ns: INode[]): number | null => {
    for (const n of ns) {
      if (n.t === 'text') {
        if (visible <= v + n.v.length) return r + (n.raw.length - n.v.length) + (visible - v);
        v += n.v.length;
        r += n.raw.length;
      } else if (n.t === 'code') {
        r += n.open.length;
        if (visible <= v + n.v.length) return r + (visible - v);
        v += n.v.length;
        r += n.v.length + n.close.length;
      } else if (n.t === 'img') {
        r += n.raw.length;
      } else {
        r += n.t === 'link' ? n.open.length : n.mark.length;
        const hit = go(n.children);
        if (hit !== null) return hit;
        r += n.t === 'link' ? n.close.length : n.mark.length;
      }
    }
    return null;
  };
  return go(parseInline(src)) ?? src.length;
}
