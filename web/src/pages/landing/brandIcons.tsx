/** 顶栏与社群弹层用到的品牌图标（路径取自设计稿 08 顶栏与社群，16×16） */

type IconProps = { className?: string };

export function GithubIcon({ className }: IconProps) {
  return (
    <svg aria-hidden viewBox="0 0 16 16" width={16} height={16} className={className} fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

export function WechatIcon({ className }: IconProps) {
  return (
    <svg aria-hidden viewBox="0 0 16 16" width={16} height={16} className={className} fill="currentColor">
      <path
        transform="translate(1.33 2.67)"
        d="M5 0C2.24 0 0 1.87 0 4.17c0 1.31.73 2.48 1.88 3.24L1.4 9l1.83-.93c.55.16 1.15.25 1.77.25.17 0 .33-.01.49-.02a3.4 3.4 0 0 1-.16-1.03c0-2.13 2.07-3.87 4.63-3.87h.29C9.77 1.37 7.6 0 5 0Zm-1.73 2.2a.67.67 0 1 1 0 1.33.67.67 0 0 1 0-1.33Zm3.46 0a.67.67 0 1 1 0 1.33.67.67 0 0 1 0-1.33Zm3.24 1.87c-2.23 0-4.04 1.46-4.04 3.26 0 1.8 1.81 3.27 4.04 3.27.46 0 .91-.07 1.33-.19l1.57.79-.4-1.35C13 9.27 14 8.4 14 7.33c0-1.8-1.81-3.26-4.03-3.26ZM8.6 5.93a.57.57 0 1 1 0 1.14.57.57 0 0 1 0-1.14Zm2.73 0a.57.57 0 1 1 0 1.14.57.57 0 0 1 0-1.14Z"
      />
    </svg>
  );
}

export function QqIcon({ className }: IconProps) {
  return (
    <svg aria-hidden viewBox="0 0 16 16" width={16} height={16} className={className} fill="currentColor">
      <path
        transform="translate(2.77 1.33)"
        d="M5.23 0C3.03 0 1.5 1.73 1.5 4v.8C.9 5.47.23 6.53.03 7.73c-.13.8.2 1.2.47 1.07.27-.13.6-.6.87-1.07.2.87.67 1.67 1.27 2.27-.74.27-1.27.67-1.27 1.2 0 .67 1.27 1.13 2.73 1.13.8 0 1.54-.13 2-.4h.94c.46.27 1.2.4 2 .4 1.46 0 2.73-.46 2.73-1.13 0-.53-.53-.93-1.27-1.2.6-.6 1.07-1.4 1.27-2.27.27.47.6.94.87 1.07.26.13.6-.27.46-1.07-.2-1.2-.86-2.26-1.46-2.93V4c0-2.27-1.54-4-3.74-4H5.23Z"
      />
    </svg>
  );
}

export function QrIcon({ className, size = 16 }: IconProps & { size?: number }) {
  return (
    <svg aria-hidden viewBox="0 0 16 16" width={size} height={size} className={className} fill="none" stroke="currentColor" strokeWidth={1.27} strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="4" height="4" rx="0.8" />
      <rect x="10" y="2" width="4" height="4" rx="0.8" />
      <rect x="2" y="10" width="4" height="4" rx="0.8" />
      <path d="M10 10h1.67v1.67M14 10v.01M10 14h.01M12 14h2v-2M8 2v2M8 6v2H6M2 8h2" />
    </svg>
  );
}
