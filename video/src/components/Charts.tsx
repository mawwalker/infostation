import React from 'react';
import {C, FONT, panelStyle} from '../theme';
import {fmtPrice} from '../format';
import type {Candle} from '../types';
import {progress, slideUp, useEnter, useT} from '../anim';

export const Panel: React.FC<{title?: string; style?: React.CSSProperties; delay?: number; children: React.ReactNode}> = ({title, style, delay = 0, children}) => {
  const p = useEnter(delay);
  return (
    <div style={{...panelStyle, padding: '22px 28px', fontFamily: FONT, color: C.text, ...slideUp(p), ...style}}>
      {title ? <div style={{fontSize: 22, fontWeight: 700, color: C.sub, letterSpacing: 1, marginBottom: 14, textTransform: 'uppercase'}}>{title}</div> : null}
      {children}
    </div>
  );
};

export const Bullets: React.FC<{items: string[]; delay?: number; size?: number; stagger?: number}> = ({items, delay = 0, size = 30, stagger = 12}) => (
  <div style={{display: 'flex', flexDirection: 'column', gap: 18}}>
    {items.map((b, i) => <BulletRow key={i} text={b} delay={delay + i * stagger} size={size} />)}
  </div>
);

const BulletRow: React.FC<{text: string; delay: number; size: number}> = ({text, delay, size}) => {
  const p = useEnter(delay);
  return (
    <div style={{display: 'flex', gap: 16, alignItems: 'flex-start', fontSize: size, lineHeight: 1.35, fontWeight: 500, ...slideUp(p, 20)}}>
      <div style={{width: 10, height: 10, borderRadius: 5, marginTop: size * 0.45, flexShrink: 0, background: `linear-gradient(135deg, ${C.accent}, ${C.accent2})`}} />
      <div>{text}</div>
    </div>
  );
};

export const Sparkline: React.FC<{data: number[]; width: number; height: number; color: string; delay?: number; dur?: number}> = ({data, width, height, color, delay = 0, dur = 40}) => {
  const t = useT();
  const p = progress(t, delay, dur);
  if (data.length < 2) return <svg width={width} height={height} />;
  const min = Math.min(...data), max = Math.max(...data);
  const pts = data.map((v, i) => [i / (data.length - 1) * width, height - 4 - ((v - min) / (max - min || 1)) * (height - 8)]);
  const d = pts.map((pt, i) => `${i ? 'L' : 'M'}${pt[0].toFixed(1)},${pt[1].toFixed(1)}`).join(' ');
  const id = `sg${Math.round(data[0] * 1000)}${data.length}`;
  return (
    <svg width={width} height={height}>
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.35} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
        <clipPath id={`${id}c`}><rect x={0} y={0} width={width * p} height={height} /></clipPath>
      </defs>
      <g clipPath={`url(#${id}c)`}>
        <path d={`${d} L${width},${height} L0,${height} Z`} fill={`url(#${id})`} />
        <path d={d} fill="none" stroke={color} strokeWidth={3} strokeLinejoin="round" />
      </g>
    </svg>
  );
};

export const CandleChart: React.FC<{data: Candle[]; width: number; height: number; colors: {up: string; down: string}; delay?: number; dur?: number}> = ({data, width, height, colors, delay = 0, dur = 75}) => {
  const t = useT();
  const shown = Math.max(1, Math.ceil(progress(t, delay, dur) * data.length));
  const padR = 110, padB = 26, volH = height * 0.18;
  const priceH = height - volH - padB - 10;
  const lo = Math.min(...data.map((c) => c.low)), hi = Math.max(...data.map((c) => c.high));
  const vmax = Math.max(...data.map((c) => c.volume)) || 1;
  const cw = (width - padR) / data.length;
  const y = (v: number) => 8 + (hi - v) / (hi - lo || 1) * (priceH - 16);
  const last = data[shown - 1];
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => lo + (hi - lo) * f);
  return (
    <svg width={width} height={height} style={{fontFamily: FONT}}>
      {ticks.map((v, i) => (
        <g key={i}>
          <line x1={0} x2={width - padR} y1={y(v)} y2={y(v)} stroke={C.grid} strokeWidth={1} />
          <text x={width - padR + 12} y={y(v) + 7} fill={C.faint} fontSize={18}>{fmtPrice(v)}</text>
        </g>
      ))}
      {data.slice(0, shown).map((c, i) => {
        const up = c.close >= c.open;
        const col = up ? colors.up : colors.down;
        const x = i * cw + cw / 2;
        const bodyTop = y(Math.max(c.open, c.close));
        const bodyH = Math.max(2, Math.abs(y(c.open) - y(c.close)));
        const vh = (c.volume / vmax) * volH;
        return (
          <g key={c.date}>
            <line x1={x} x2={x} y1={y(c.high)} y2={y(c.low)} stroke={col} strokeWidth={2} />
            <rect x={x - cw * 0.34} y={bodyTop} width={cw * 0.68} height={bodyH} fill={col} rx={1.5} />
            <rect x={x - cw * 0.34} y={height - padB - vh} width={cw * 0.68} height={vh} fill={col} opacity={0.35} />
          </g>
        );
      })}
      {last ? (
        <g>
          <line x1={0} x2={width - padR} y1={y(last.close)} y2={y(last.close)} stroke={C.text} strokeDasharray="6 6" strokeOpacity={0.4} />
          <rect x={width - padR + 4} y={y(last.close) - 18} width={padR - 6} height={36} rx={8} fill={last.close >= last.open ? colors.up : colors.down} />
          <text x={width - padR + 14} y={y(last.close) + 8} fill="#fff" fontSize={20} fontWeight={700}>{fmtPrice(last.close)}</text>
        </g>
      ) : null}
      <text x={0} y={height - 4} fill={C.faint} fontSize={17}>{data[0]?.date}</text>
      <text x={width - padR} y={height - 4} fill={C.faint} fontSize={17} textAnchor="end">{data[data.length - 1]?.date}</text>
    </svg>
  );
};

export const AreaChart: React.FC<{data: {date: string; close: number}[]; width: number; height: number; color: string; delay?: number}> = ({data, width, height, color, delay = 0}) => {
  const t = useT();
  const p = progress(t, delay, 60);
  if (data.length < 2) return null;
  const vals = data.map((d) => d.close);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const padR = 120;
  const w = width - padR;
  const y = (v: number) => 10 + (hi - v) / (hi - lo || 1) * (height - 50);
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${y(v).toFixed(1)}`);
  return (
    <svg width={width} height={height} style={{fontFamily: FONT}}>
      <defs>
        <linearGradient id="areag" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.4} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
        <clipPath id="areac"><rect x={0} y={0} width={w * p + 2} height={height} /></clipPath>
      </defs>
      {[lo, (lo + hi) / 2, hi].map((v, i) => (
        <g key={i}>
          <line x1={0} x2={w} y1={y(v)} y2={y(v)} stroke={C.grid} />
          <text x={w + 12} y={y(v) + 7} fill={C.faint} fontSize={18}>{fmtPrice(v)}</text>
        </g>
      ))}
      <g clipPath="url(#areac)">
        <polygon points={`0,${height - 40} ${pts.join(' ')} ${w},${height - 40}`} fill="url(#areag)" />
        <polyline points={pts.join(' ')} fill="none" stroke={color} strokeWidth={3.5} strokeLinejoin="round" />
      </g>
      <text x={0} y={height - 8} fill={C.faint} fontSize={17}>{data[0].date}</text>
      <text x={w} y={height - 8} fill={C.faint} fontSize={17} textAnchor="end">{data[data.length - 1].date}</text>
    </svg>
  );
};

export const Gauge: React.FC<{value: number; size: number; delay?: number; colors: {up: string; down: string}; label?: string}> = ({value, size, delay = 0, colors, label}) => {
  const t = useT();
  const v = value * progress(t, delay, 45);
  const r = size / 2 - 14, cx = size / 2, cy = size / 2 + 6;
  const ang = Math.PI * (1 - v / 100);
  const arc = (a0: number, a1: number) => {
    const p0 = [cx + r * Math.cos(a0), cy - r * Math.sin(a0)], p1 = [cx + r * Math.cos(a1), cy - r * Math.sin(a1)];
    return `M${p0[0]},${p0[1]} A${r},${r} 0 0 1 ${p1[0]},${p1[1]}`;
  };
  return (
    <svg width={size} height={size / 2 + 40} style={{fontFamily: FONT}}>
      <defs>
        <linearGradient id="gg" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor={colors.down} />
          <stop offset="50%" stopColor={C.gold} />
          <stop offset="100%" stopColor={colors.up} />
        </linearGradient>
      </defs>
      <path d={arc(Math.PI, 0)} stroke="rgba(255,255,255,0.08)" strokeWidth={18} fill="none" strokeLinecap="round" />
      <path d={arc(Math.PI, ang)} stroke="url(#gg)" strokeWidth={18} fill="none" strokeLinecap="round" />
      <line x1={cx} y1={cy} x2={cx + (r - 26) * Math.cos(ang)} y2={cy - (r - 26) * Math.sin(ang)} stroke={C.text} strokeWidth={4} strokeLinecap="round" />
      <circle cx={cx} cy={cy} r={8} fill={C.text} />
      <text x={cx} y={cy + 36} fill={C.text} fontSize={34} fontWeight={800} textAnchor="middle">{Math.round(v)}</text>
      {label ? <text x={cx} y={cy - r / 2.4} fill={C.sub} fontSize={18} textAnchor="middle">{label}</text> : null}
    </svg>
  );
};
