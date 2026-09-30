import { Check, ImagePlus, X } from 'lucide-react';
import { useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { feedbackApi, type FeedbackDTO, type FeedbackTypeDTO } from '@/api/endpoints';
import { ApiError, USE_MOCK } from '@/api/http';
import { useToast } from '@/contexts/ToastContext';
import { cn } from '@/lib/cn';
import { COMMUNITY, ISSUES_URL, PageIntro, pill, SECURITY_EMAIL, SECURITY_URL } from '@/pages/landing/shared';
import { PublicShell, SCROLL_ROOT_ID } from '@/pages/landing/SiteChrome';

/**
 * 反馈与建议（设计稿「11 反馈」L13 表单 / L13b 状态）。
 * 提交到 B10 匿名接口 POST /api/v1/feedback：后端只有 type / title / content / file 四个字段，
 * 联系邮箱拼进 content 末尾，附件只支持 1 张截图。
 */

const TYPES: { value: FeedbackTypeDTO; label: string; icon: string; desc: string }[] = [
  { value: 'BUG', label: '问题反馈', icon: '!', desc: '功能异常、报错、结果不对' },
  { value: 'FEATURE', label: '功能建议', icon: '+', desc: '希望新增或改进的能力' },
  { value: 'OTHER', label: '使用咨询', icon: '?', desc: '部署、配置与接入问题' },
];

const TITLE_MAX = 128;
const CONTENT_MIN = 10;
const CONTENT_MAX = 2000;
const FILE_MAX = 5 * 1024 * 1024;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Errors = Partial<Record<'title' | 'content' | 'email' | 'file', string>>;

const ext = { target: '_blank', rel: 'noreferrer noopener' } as const;

export default function FeedbackPage() {
  const [done, setDone] = useState<FeedbackDTO | null>(null);
  return (
    <PublicShell>
      <PageIntro title="反馈与建议" desc="遇到问题或有想法，都可以告诉我们。每条反馈都会被阅读，问题类会在 GitHub 上公开跟进。" />
      <div className="mx-auto flex max-w-[1440px] flex-col gap-10 px-5 pb-[88px] md:px-[100px] lg:flex-row lg:items-start lg:gap-14">
        <div className="w-full lg:w-[624px] lg:shrink-0">{done ? <Success result={done} onAgain={() => setDone(null)} /> : <FeedbackForm onDone={setDone} />}</div>
        <Aside />
      </div>
    </PublicShell>
  );
}

function Label({ htmlFor, required, children }: { htmlFor?: string; required?: boolean; children: React.ReactNode }) {
  const Tag = htmlFor ? 'label' : 'span';
  return (
    <Tag htmlFor={htmlFor} className="flex gap-1 text-[13.5px] font-medium text-ink">
      {children}
      {required && (
        <span aria-hidden className="text-[#c86a5a]">
          *
        </span>
      )}
    </Tag>
  );
}

function ErrorText({ id, children }: { id: string; children?: string }) {
  if (!children) return null;
  return (
    <p id={id} className="text-[12px] text-[#c86a5a]">
      {children}
    </p>
  );
}

const field = (invalid?: boolean) =>
  cn('w-full rounded-xl border bg-white px-3.5 text-[14px] text-ink outline-none transition-colors placeholder:text-[#b5b4ac] focus:border-brand', invalid ? 'border-[#c86a5a]' : 'border-line hover:border-[#c9c8c0]');

function FeedbackForm({ onDone }: { onDone: (r: FeedbackDTO) => void }) {
  const toast = useToast();
  const id = useId();
  const [type, setType] = useState<FeedbackTypeDTO>('BUG');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [email, setEmail] = useState('');
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const contentRef = useRef<HTMLTextAreaElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  const validate = (): Errors => {
    const e: Errors = {};
    if (!title.trim()) e.title = '请填写标题';
    else if (title.trim().length > TITLE_MAX) e.title = `标题不超过 ${TITLE_MAX} 个字`;
    if (content.trim().length < CONTENT_MIN) e.content = `请至少写 ${CONTENT_MIN} 个字`;
    if (email.trim() && !EMAIL_RE.test(email.trim())) e.email = '邮箱格式不正确';
    return e;
  };

  const pickFile = (f?: File | null) => {
    if (!f) return;
    if (!/^image\/(png|jpeg)$/.test(f.type)) return setErrors((e) => ({ ...e, file: '只支持 PNG / JPG 图片' }));
    if (f.size > FILE_MAX) return setErrors((e) => ({ ...e, file: '图片不能超过 5 MB' }));
    setErrors((e) => ({ ...e, file: undefined }));
    setFile(f);
  };

  const body = () => {
    return email.trim() ? `${content.trim()}\n\n---\n联系邮箱：${email.trim()}` : content.trim();
  };

  const submit = async () => {
    const e = validate();
    setErrors(e);
    if (e.title) return titleRef.current?.focus();
    if (e.content) return contentRef.current?.focus();
    if (e.email) return emailRef.current?.focus();
    setSubmitting(true);
    try {
      const res = USE_MOCK
        ? await new Promise<FeedbackDTO>((r) => setTimeout(() => r({ id: Math.floor(Math.random() * 900) + 100, type, title: title.trim(), status: 'PENDING', createdAt: new Date().toISOString() }), 600))
        : await feedbackApi.submit({ type, title: title.trim(), content: body(), file: file ?? undefined });
      onDone(res);
      document.getElementById(SCROLL_ROOT_ID)?.scrollTo({ top: 0 });
    } catch (err) {
      // 后端未开启反馈写入（503）时引导到 GitHub Issues；其余错误保留已填内容并可重试
      const closed = err instanceof ApiError && err.status === 503;
      toast(closed ? '站内反馈暂未开放，可以先到 GitHub Issues 提交。' : '提交失败，请检查网络后重试。已填写内容已保留。', {
        tone: 'error',
        action: closed ? { label: '打开 Issues', onClick: () => window.open(newIssueUrl(title, body()), '_blank', 'noopener') } : { label: '重试', onClick: submit },
      });
    } finally {
      setSubmitting(false);
    }
  };

  const count = content.length;
  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        if (!submitting) submit();
      }}
      className="flex flex-col gap-[22px] rounded-[20px] border border-divider bg-white p-5 sm:p-8"
    >
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-2">
          <Label required>反馈类型</Label>
        </legend>
        <div role="radiogroup" aria-label="反馈类型" className="grid gap-3 sm:grid-cols-3">
          {TYPES.map((t) => {
            const on = t.value === type;
            return (
              <button
                key={t.value}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => setType(t.value)}
                className={cn('flex flex-col gap-1.5 rounded-[14px] border p-3.5 text-left transition-colors', on ? 'border-brand bg-brand-soft' : 'border-line bg-white hover:border-[#c9c8c0]')}
              >
                <span className="flex items-center gap-2">
                  <span aria-hidden className={cn('w-2.5 text-center font-num text-[15px]', on ? 'text-brand' : 'text-muted')}>
                    {t.icon}
                  </span>
                  <span className="text-[14px] font-medium text-ink">{t.label}</span>
                </span>
                <span className="text-[12px] leading-[18px] text-muted">{t.desc}</span>
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className="flex flex-col gap-2">
        <Label htmlFor={`${id}-title`} required>
          标题
        </Label>
        <input
          ref={titleRef}
          id={`${id}-title`}
          value={title}
          maxLength={TITLE_MAX}
          onChange={(e) => {
            setTitle(e.target.value);
            if (errors.title) setErrors((x) => ({ ...x, title: undefined }));
          }}
          aria-invalid={!!errors.title}
          aria-describedby={errors.title ? `${id}-title-err` : undefined}
          placeholder="一句话概括，例如「上传 DOCX 后解析卡在 90%」"
          className={cn(field(!!errors.title), 'h-[42px]')}
        />
        <ErrorText id={`${id}-title-err`}>{errors.title}</ErrorText>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor={`${id}-content`} required>
          详细描述
        </Label>
        <div className={cn(field(!!errors.content), 'flex flex-col py-3 focus-within:border-brand')}>
          <textarea
            ref={contentRef}
            id={`${id}-content`}
            value={content}
            maxLength={CONTENT_MAX}
            rows={5}
            onChange={(e) => {
              setContent(e.target.value);
              if (errors.content) setErrors((x) => ({ ...x, content: undefined }));
            }}
            aria-invalid={!!errors.content}
            aria-describedby={`${id}-count${errors.content ? ` ${id}-content-err` : ''}`}
            placeholder="描述你遇到的情况：做了什么操作、期望的结果、实际的结果。"
            className="min-h-[110px] resize-y bg-transparent text-[14px] leading-[22px] outline-none placeholder:text-[#b5b4ac]"
          />
          <span id={`${id}-count`} className="self-end font-num text-[11.5px] text-[#b5b4ac]">
            {count} / {CONTENT_MAX}
          </span>
        </div>
        <ErrorText id={`${id}-content-err`}>{errors.content}</ErrorText>
      </div>

      <div className="flex flex-col gap-2">
        <Label>截图（可选）</Label>
        {file ? (
          <div className="flex items-center gap-3 rounded-xl border border-line bg-[#fbfbf9] px-4 py-3">
            <ImagePlus aria-hidden className="size-4 text-muted" />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-[13px] font-medium text-ink">{file.name}</span>
              <span className="font-num text-[12px] text-muted">{(file.size / 1024).toFixed(0)} KB</span>
            </span>
            <button type="button" onClick={() => setFile(null)} aria-label="移除截图" className="flex size-7 items-center justify-center rounded-full text-muted hover:bg-soft hover:text-ink">
              <X aria-hidden className="size-3.5" />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              pickFile(e.dataTransfer.files[0]);
            }}
            className={cn('flex items-center gap-3 rounded-xl border border-dashed px-4 py-3.5 text-left transition-colors', dragging ? 'border-brand bg-brand-soft' : 'border-line bg-[#fbfbf9] hover:border-[#c9c8c0]')}
          >
            <span aria-hidden className="text-[16px] text-muted">
              ⤒
            </span>
            <span className="flex flex-col gap-0.5">
              <span className="text-[13px] font-medium text-ink">拖入或点击上传截图</span>
              <span className="text-[12px] text-muted">PNG / JPG，1 张，不超过 5 MB</span>
            </span>
          </button>
        )}
        <input ref={fileInput} type="file" accept="image/png,image/jpeg" hidden onChange={(e) => pickFile(e.target.files?.[0])} />
        <ErrorText id={`${id}-file-err`}>{errors.file}</ErrorText>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor={`${id}-email`}>联系邮箱（可选）</Label>
        <input
          ref={emailRef}
          id={`${id}-email`}
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
            if (errors.email) setErrors((x) => ({ ...x, email: undefined }));
          }}
          aria-invalid={!!errors.email}
          aria-describedby={`${id}-email-hint`}
          placeholder="用于回复处理进展"
          className={cn(field(!!errors.email), 'h-[42px]')}
        />
        {errors.email ? <ErrorText id={`${id}-email-hint`}>{errors.email}</ErrorText> : <p id={`${id}-email-hint`} className="text-[12px] text-muted">只用于回复本条反馈，不会用于营销。</p>}
      </div>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center">
        <p className="flex-1 text-[12px] text-muted">提交即表示同意在必要时公开脱敏后的问题描述。</p>
        <button type="submit" disabled={submitting} aria-busy={submitting} className={cn(pill.primary, 'px-6 py-[11px] text-[14px] disabled:cursor-not-allowed disabled:bg-[#c9b49c] disabled:shadow-none')}>
          {submitting ? '提交中…' : '提交反馈'}
        </button>
      </div>
    </form>
  );
}

function Success({ result, onAgain }: { result: FeedbackDTO; onAgain: () => void }) {
  const code = `#FB-${(result.createdAt ?? '').slice(0, 10).replaceAll('-', '')}-${String(result.id).padStart(4, '0')}`;
  return (
    <section aria-live="polite" className="flex animate-rise-in flex-col items-start gap-3.5 rounded-[20px] border border-divider bg-white px-6 py-12 sm:px-10">
      <span aria-hidden className="flex size-12 items-center justify-center rounded-full bg-brand-soft text-brand">
        <Check className="size-5" strokeWidth={2.5} />
      </span>
      <h2 className="font-serif text-[26px] font-semibold text-ink">已收到你的反馈</h2>
      <p className="text-[14px] leading-[23px] text-text2">
        编号 <span className="font-num font-medium text-ink">{code}</span>。维护者会尽快查看并分类；留了邮箱的话，处理进展会发到你的邮箱。
      </p>
      <p className="flex items-center gap-2.5 rounded-xl bg-soft px-4 py-3 text-[13px] text-text2">
        问题类反馈会在 GitHub Issues 公开跟进
        <a href={ISSUES_URL} {...ext} className="font-medium text-[#a8733f] hover:underline">
          查看 Issues ↗
        </a>
      </p>
      <div className="mt-1 flex gap-2.5">
        <button type="button" onClick={onAgain} className={cn(pill.secondary, 'px-5 py-2.5 text-[14px]')}>
          再提交一条
        </button>
        <Link to="/" className={cn(pill.primary, 'px-5 py-2.5 text-[14px]')}>
          返回首页
        </Link>
      </div>
    </section>
  );
}

function Aside() {
  const card = 'flex flex-col gap-1.5 rounded-2xl border border-divider bg-white p-5';
  const hasGroup = !!(COMMUNITY.wechatQr || COMMUNITY.qqQr || COMMUNITY.wechatId || COMMUNITY.qqJoinUrl);
  return (
    <aside aria-label="其他渠道" className="flex w-full flex-col gap-4 lg:sticky lg:top-24 lg:w-[420px] [@media(max-height:640px)]:static">
      <section className={cn(card, 'gap-3')}>
        <h2 className="text-[14.5px] font-medium text-ink">提交后会发生什么</h2>
        <ol className="flex flex-col gap-3">
          {['维护者确认收到并分类', '问题类在 GitHub Issues 同步跟踪', '留了邮箱的，处理进展会邮件告知'].map((s, i) => (
            <li key={s} className="flex items-center gap-2.5 text-[13px] text-text2">
              <span className="flex h-[17px] min-w-5 items-center justify-center rounded-full bg-soft px-1.5 font-num text-[11px] font-medium text-text2">{i + 1}</span>
              {s}
            </li>
          ))}
        </ol>
      </section>
      <section className={card}>
        <h2 className="text-[14.5px] font-medium text-ink">先搜一搜已有 Issue</h2>
        <p className="text-[13px] leading-[21px] text-text2">同样的问题可能已经有人提过，补充信息比新开一条更快。</p>
        <a href={ISSUES_URL} {...ext} className="text-[13px] font-medium text-[#a8733f] hover:underline">
          打开 GitHub Issues ↗
        </a>
      </section>
      <section className={card}>
        <h2 className="text-[14.5px] font-medium text-ink">安全问题</h2>
        <p className="text-[13px] leading-[21px] text-text2">涉及漏洞或数据泄露，请勿公开提交，{SECURITY_EMAIL ? '发送至安全邮箱。' : '请通过 GitHub 私密漏洞报告提交。'}</p>
        <a href={SECURITY_URL} {...(SECURITY_EMAIL ? {} : ext)} className="text-[13px] font-medium text-[#a8733f] hover:underline">
          {SECURITY_EMAIL ?? '私密报告漏洞 ↗'}
        </a>
      </section>
      {hasGroup && (
        <section className="flex flex-col gap-1 rounded-2xl bg-brand-soft p-5">
          <h2 className="text-[14px] font-medium text-ink">想更快得到回复？</h2>
          <p className="text-[12.5px] text-text2">加入微信 / QQ 交流群，点击顶栏「社群」查看入群方式。</p>
        </section>
      )}
    </aside>
  );
}

/** 后端未开启时的兜底：带标题与正文预填的新 Issue 链接（正文截断，避免 URL 过长） */
function newIssueUrl(title: string, body: string) {
  const q = new URLSearchParams({ title: title.trim(), body: body.slice(0, 1500) });
  return `${ISSUES_URL}/new?${q}`;
}
