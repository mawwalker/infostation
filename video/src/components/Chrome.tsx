import React from 'react';
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {C, FONT, LAYOUT} from '../theme';
import {fmtPct, toneColor} from '../format';
import type {Caption} from '../types';

export const Background: React.FC<{bgImage: string | null}> = ({bgImage}) => {
  const frame = useCurrentFrame();
  const drift = Math.sin(frame / 240) * 60;
  return (
    <AbsoluteFill style={{background: `radial-gradient(ellipse at 20% 0%, ${C.bg1} 0%, ${C.bg0} 70%)`}}>
      {bgImage ? (
        <Img src={staticFile(bgImage)} style={{width: '100%', height: '100%', objectFit: 'cover', opacity: 0.18, filter: 'blur(2px) saturate(0.8)'}} />
      ) : null}
      <svg width="100%" height="100%" style={{position: 'absolute', inset: 0}}>
        <defs>
          <pattern id="grid" width="64" height="64" patternUnits="userSpaceOnUse">
            <path d="M 64 0 L 0 0 0 64" fill="none" stroke={C.grid} strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" />
      </svg>
      <div style={{position: 'absolute', width: 900, height: 900, borderRadius: 450, left: 1300 + drift, top: -380,
        background: 'radial-gradient(circle, rgba(79,140,255,0.16), transparent 65%)'}} />
      <div style={{position: 'absolute', width: 800, height: 800, borderRadius: 400, left: -300 - drift, top: 600,
        background: 'radial-gradient(circle, rgba(164,107,255,0.10), transparent 65%)'}} />
    </AbsoluteFill>
  );
};

export const Header: React.FC<{brand: string; chapter: string; dateLabel: string; sessionLabel: string}> = ({brand, chapter, dateLabel, sessionLabel}) => (
  <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: LAYOUT.headerH, display: 'flex', alignItems: 'center',
    padding: `0 ${LAYOUT.side}px`, fontFamily: FONT, color: C.text, borderBottom: `1px solid ${C.panelBorder}`,
    background: 'linear-gradient(180deg, rgba(6,10,18,0.9), rgba(6,10,18,0.4))'}}>
    <div style={{display: 'flex', alignItems: 'center', gap: 16}}>
      <div style={{width: 44, height: 44, borderRadius: 12, background: `linear-gradient(135deg, ${C.accent}, ${C.accent2})`,
        display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: 24}}>◆</div>
      <div style={{fontSize: 30, fontWeight: 700, letterSpacing: 0.5}}>{brand}</div>
    </div>
    <div style={{flex: 1, textAlign: 'center', fontSize: 28, fontWeight: 600, color: C.sub, letterSpacing: 1}}>{chapter}</div>
    <div style={{textAlign: 'right'}}>
      <div style={{fontSize: 24, fontWeight: 600}}>{dateLabel}</div>
      <div style={{fontSize: 20, color: C.accent, fontWeight: 600}}>{sessionLabel}</div>
    </div>
  </div>
);

export const Captions: React.FC<{captions: Caption[]; lang: 'zh' | 'en'}> = ({captions, lang}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const cur = captions.find((c) => t >= c.start && t < c.end);
  if (!cur) return null;
  // Fade only on the first cue after silence; consecutive cues cut cleanly like broadcast subtitles.
  const prev = captions[captions.indexOf(cur) - 1];
  const fadeIn = !prev || cur.start - prev.end > 0.1;
  const p = fadeIn ? interpolate(t, [cur.start, cur.start + 0.1], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) : 1;
  const zh = lang === 'zh';
  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom: 74, display: 'flex', justifyContent: 'center', fontFamily: FONT}}>
      <div style={{maxWidth: 1500, padding: zh ? '12px 34px' : '10px 30px', borderRadius: 14, background: 'rgba(4,7,14,0.72)',
        color: '#ffffff', fontSize: zh ? 44 : 40, fontWeight: zh ? 600 : 500, lineHeight: zh ? 1.3 : 1.28,
        letterSpacing: zh ? 1.5 : 0.2, textAlign: 'center', whiteSpace: 'pre-line', opacity: p,
        textShadow: '0 2px 6px rgba(0,0,0,0.55)'}}>
        {cur.text}
      </div>
    </div>
  );
};

export const Tape: React.FC<{items: {label: string; change_pct: number}[]; colors: {up: string; down: string}}> = ({items, colors}) => {
  const frame = useCurrentFrame();
  if (!items.length) return null;
  const itemW = 300;
  const loopW = items.length * itemW;
  const x = -((frame * 2.2) % loopW);
  const row = [...items, ...items, ...items];
  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 52, overflow: 'hidden', fontFamily: FONT,
      background: 'rgba(4,7,14,0.92)', borderTop: `1px solid ${C.panelBorder}`}}>
      <div style={{position: 'absolute', left: x, top: 0, height: 52, display: 'flex', alignItems: 'center'}}>
        {row.map((it, i) => (
          <div key={i} style={{width: itemW, display: 'flex', gap: 14, justifyContent: 'center', fontSize: 22, fontWeight: 600}}>
            <span style={{color: C.sub}}>{it.label}</span>
            <span style={{color: toneColor(it.change_pct, colors), fontVariantNumeric: 'tabular-nums'}}>{fmtPct(it.change_pct)}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

export const ChapterProgress: React.FC<{chapters: {title: string; from: number; dur: number}[]; total: number}> = ({chapters, total}) => {
  const frame = useCurrentFrame();
  return (
    <div style={{position: 'absolute', left: 0, right: 0, top: LAYOUT.headerH, height: 4, display: 'flex', gap: 3}}>
      {chapters.map((c, i) => {
        const p = Math.max(0, Math.min(1, (frame - c.from) / c.dur));
        return (
          <div key={i} style={{flex: c.dur / total, background: 'rgba(255,255,255,0.08)'}}>
            <div style={{width: `${p * 100}%`, height: '100%', background: `linear-gradient(90deg, ${C.accent}, ${C.accent2})`}} />
          </div>
        );
      })}
    </div>
  );
};
