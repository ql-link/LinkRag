import { useId, useState } from 'react';

import type { DashboardDTO } from '../api';
import { fmt } from '../ui';

const W = 675;
const H = 250;
const LEFT = 34;
const BASE = 226;

/** 设计稿 B1 用户趋势：活跃（墨色 + 面积）/ 新增（灰色）双折线，4 条水平刻度 */
export function TrendChart({ trend }: { trend: DashboardDTO['trend'] }) {
  const id = useId();
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(4, ...trend.map((t) => Math.max(t.activeUsers, t.newUsers)));
  const top = Math.ceil(max / 3) * 3;
  const step = (W - LEFT - 8) / Math.max(1, trend.length - 1);
  const x = (i: number) => LEFT + i * step;
  const y = (v: number) => BASE - (v / top) * BASE;
  const line = (k: 'activeUsers' | 'newUsers') => trend.map((t, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(t[k]).toFixed(1)}`).join('');
  const labels = [0, Math.round(trend.length / 4), Math.round(trend.length / 2), Math.round((trend.length * 3) / 4), trend.length - 1];
  const h = hover === null ? null : trend[hover];
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="用户趋势折线图" onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#1d1d1b" stopOpacity="0.08" />
            <stop offset="1" stopColor="#1d1d1b" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3].map((k) => {
          const v = (top / 3) * k;
          return (
            <g key={k}>
              <line x1={LEFT} x2={W} y1={y(v)} y2={y(v)} stroke={k ? '#ececea' : '#e4e4e0'} />
              <text x={0} y={y(v) + 3.5} className="fill-muted font-num text-[10px] font-medium">
                {fmt(Math.round(v))}
              </text>
            </g>
          );
        })}
        {trend.length > 0 && (
          <>
            <path d={`${line('activeUsers')}L${x(trend.length - 1)},${BASE}L${LEFT},${BASE}Z`} fill={`url(#${id})`} />
            <path d={line('activeUsers')} fill="none" stroke="#1d1d1b" strokeWidth="2" strokeLinejoin="round" />
            <path d={line('newUsers')} fill="none" stroke="#a8a8a2" strokeWidth="1.5" strokeLinejoin="round" />
            <circle cx={x(trend.length - 1)} cy={y(trend[trend.length - 1].activeUsers)} r="4" fill="#1d1d1b" stroke="#fff" strokeWidth="2" />
          </>
        )}
        {[...new Set(labels)].map((i) =>
          trend[i] ? (
            <text key={i} x={x(i)} y={H - 3} textAnchor={i === 0 ? 'start' : i === trend.length - 1 ? 'end' : 'middle'} className="fill-muted font-num text-[10px] font-medium">
              {trend[i].date.slice(5).replace('-', '/')}
            </text>
          ) : null,
        )}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={BASE} stroke="#dcdcd8" strokeDasharray="3 3" />}
        {trend.map((_, i) => (
          <rect key={i} x={x(i) - step / 2} y={0} width={step} height={BASE} fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
      </svg>
      {h && hover !== null && (
        <div className="pointer-events-none absolute top-2 rounded-[8px] border border-divider bg-white px-2.5 py-1.5 text-[11px] shadow-pop" style={{ left: `min(calc(${(x(hover) / W) * 100}% + 8px), calc(100% - 120px))` }}>
          <p className="font-num text-muted">{h.date}</p>
          <p className="text-ink">
            活跃 <span className="font-num font-medium">{fmt(h.activeUsers)}</span> · 新增 <span className="font-num font-medium">{fmt(h.newUsers)}</span>
          </p>
        </div>
      )}
    </div>
  );
}
