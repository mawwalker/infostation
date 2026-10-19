import React from 'react';
import {AbsoluteFill, Audio, Composition, Img, Sequence, staticFile, Still} from 'remotion';
import {Background, Captions, ChapterProgress, Header, Tape} from './components/Chrome';
import {SceneView} from './scenes/Scenes';
import {StaticCtx} from './anim';
import {C, FONT} from './theme';
import {fmtPct, toneColor} from './format';
import type {BriefingProps, CardProps, ThumbnailProps} from './types';

const SAMPLE: BriefingProps = {
  lang: 'en', fps: 30, width: 1920, height: 1080,
  brand: {name: 'Market Intel Daily', handle: '@handle'},
  dateLabel: 'Fri, Oct 16, 2026', sessionLabel: 'After-the-Bell Recap',
  colors: {up: '#16c784', down: '#f0454f'}, labels: {}, bgImage: null, bgm: null, bgmVolume: 0.07, tape: [],
  scenes: [{id: 'intro', type: 'intro', title: 'Sample', bullets: [], chapter: 'Intro', audio: null, durationInFrames: 90,
    captions: [], data: {theme: 'Run the pipeline to render real data', hooks: []}}],
};

const Briefing: React.FC<BriefingProps> = (p) => {
  let from = 0;
  const placed = p.scenes.map((s) => {
    const item = {s, from};
    from += s.durationInFrames;
    return item;
  });
  const chapters = placed.map(({s, from: f}) => ({title: s.chapter, from: f, dur: s.durationInFrames}));
  return (
    <AbsoluteFill style={{background: C.bg0, fontFamily: FONT}}>
      <Background bgImage={p.bgImage} />
      {p.bgm ? <Audio src={staticFile(p.bgm)} volume={p.bgmVolume} loop /> : null}
      {placed.map(({s, from: f}) => (
        <Sequence key={s.id} from={f} durationInFrames={s.durationInFrames} name={s.id}>
          <SceneView p={p} s={s} />
          {s.audio ? <Audio src={staticFile(s.audio)} /> : null}
          <Captions captions={s.captions} lang={p.lang} />
          <Header brand={p.brand.name} chapter={s.chapter} dateLabel={p.dateLabel} sessionLabel={p.sessionLabel} />
        </Sequence>
      ))}
      <ChapterProgress chapters={chapters} total={from} />
      <Tape items={p.tape} colors={p.colors} />
    </AbsoluteFill>
  );
};

const Card: React.FC<CardProps> = ({briefing: p, sceneId}) => {
  const s = p.scenes.find((x) => x.id === sceneId) ?? p.scenes[0];
  return (
    <StaticCtx.Provider value={true}>
      <AbsoluteFill style={{background: C.bg0, fontFamily: FONT}}>
        <Background bgImage={null} />
        <SceneView p={p} s={s} />
        <Header brand={p.brand.name} chapter={s.chapter} dateLabel={p.dateLabel} sessionLabel={p.sessionLabel} />
        <div style={{position: 'absolute', left: 72, right: 72, bottom: 40, display: 'flex', justifyContent: 'space-between',
          fontSize: 24, color: C.faint}}>
          <span>{p.brand.handle}</span>
          {p.footnote ? <span>{p.footnote}</span> : null}
          <span>{p.labels.nfa}</span>
        </div>
      </AbsoluteFill>
    </StaticCtx.Provider>
  );
};

const Thumbnail: React.FC<ThumbnailProps> = (t) => (
  <AbsoluteFill style={{background: `radial-gradient(ellipse at 30% 20%, #16223c, ${C.bg0} 75%)`, fontFamily: FONT, color: C.text}}>
    {t.bgImage ? <Img src={staticFile(t.bgImage)} style={{width: '100%', height: '100%', objectFit: 'cover', opacity: 0.55}} /> : null}
    <AbsoluteFill style={{background: 'linear-gradient(90deg, rgba(6,10,18,0.95) 0%, rgba(6,10,18,0.75) 55%, rgba(6,10,18,0.15) 100%)'}} />
    {t.chart.length > 1 ? <ThumbChart data={t.chart} color={toneColor(t.badges[0]?.change_pct ?? 0, t.colors)} /> : null}
    <div style={{position: 'absolute', left: 64, top: 52, display: 'flex', gap: 14, alignItems: 'center'}}>
      <div style={{padding: '8px 18px', borderRadius: 10, background: `linear-gradient(135deg, ${C.accent}, ${C.accent2})`, fontSize: 28, fontWeight: 800}}>{t.brand}</div>
      <div style={{fontSize: 28, fontWeight: 700, color: C.sub}}>{t.dateLabel}</div>
    </div>
    <div style={{position: 'absolute', left: 64, top: 150, right: 360}}>
      <div style={{fontSize: t.lang === 'zh' ? 120 : 104, fontWeight: 900, lineHeight: 1.05, letterSpacing: t.lang === 'zh' ? 2 : -1,
        textShadow: '0 6px 30px rgba(0,0,0,0.6)'}}>{t.text}</div>
      <div style={{fontSize: 36, fontWeight: 700, color: C.gold, marginTop: 22, lineHeight: 1.25, textShadow: '0 2px 12px rgba(0,0,0,0.8)'}}>{t.subtext}</div>
    </div>
    <div style={{position: 'absolute', right: 56, top: 150, display: 'flex', flexDirection: 'column', gap: 18}}>
      {t.badges.map((b) => (
        <div key={b.label} style={{width: 270, padding: '14px 20px', borderRadius: 16, background: 'rgba(6,10,18,0.82)',
          border: `2px solid ${toneColor(b.change_pct, t.colors)}`}}>
          <div style={{fontSize: 34, fontWeight: 900}}>{b.label}</div>
          <div style={{fontSize: 46, fontWeight: 900, color: toneColor(b.change_pct, t.colors)}}>{fmtPct(b.change_pct, 1)}</div>
        </div>
      ))}
    </div>
  </AbsoluteFill>
);

const ThumbChart: React.FC<{data: number[]; color: string}> = ({data, color}) => {
  const w = 860, h = 170, x0 = 40, y0 = 510;
  const lo = Math.min(...data), hi = Math.max(...data);
  const pts = data.map((v, i) => `${x0 + (i / (data.length - 1)) * w},${y0 + h - ((v - lo) / (hi - lo || 1)) * h}`);
  return (
    <svg width={1280} height={720} style={{position: 'absolute', inset: 0}}>
      <defs>
        <linearGradient id="tg" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.35} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <polygon points={`${x0},${y0 + h + 40} ${pts.join(' ')} ${x0 + w},${y0 + h + 40}`} fill="url(#tg)" />
      <polyline points={pts.join(' ')} fill="none" stroke={color} strokeWidth={6} strokeLinejoin="round" />
    </svg>
  );
};

export const Root: React.FC = () => (
  <>
    <Composition
      id="Briefing"
      component={Briefing}
      defaultProps={SAMPLE}
      fps={30}
      width={1920}
      height={1080}
      durationInFrames={90}
      calculateMetadata={({props}) => ({
        fps: props.fps,
        width: props.width,
        height: props.height,
        durationInFrames: Math.max(1, props.scenes.reduce((a, s) => a + s.durationInFrames, 0)),
      })}
    />
    <Still id="Card" component={Card} defaultProps={{briefing: SAMPLE, sceneId: 'intro'}} width={1920} height={1080} />
    <Still id="Thumbnail" component={Thumbnail} width={1280} height={720}
      defaultProps={{lang: 'en', text: 'SAMPLE', subtext: 'sub', brand: 'Brand', dateLabel: 'Oct 16', colors: SAMPLE.colors, bgImage: null, badges: [], chart: []}} />
  </>
);
