import React from 'react';
import {AbsoluteFill} from 'remotion';
import {C, FONT, LAYOUT, panelStyle} from '../theme';
import {fmtPct, fmtPrice, fmtValue, toneColor} from '../format';
import type {BriefingProps, Scene} from '../types';
import {progress, slideUp, useEnter, useT} from '../anim';
import {AreaChart, Bullets, CandleChart, Gauge, Panel, Sparkline} from '../components/Charts';

type Ctx = {p: BriefingProps};
type Colors = {up: string; down: string};

const Area: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
  <AbsoluteFill style={{top: LAYOUT.top, bottom: 1080 - LAYOUT.bottom, left: LAYOUT.side, right: LAYOUT.side,
    width: 'auto', height: 'auto', fontFamily: FONT, color: C.text, ...style}}>
    {children}
  </AbsoluteFill>
);

const SceneTitle: React.FC<{title: string; kicker?: string}> = ({title, kicker}) => {
  const p = useEnter(0);
  return (
    <div style={{marginBottom: 26, ...slideUp(p, 24)}}>
      {kicker ? <div style={{fontSize: 22, color: C.accent, fontWeight: 700, letterSpacing: 2, marginBottom: 6}}>{kicker}</div> : null}
      <div style={{fontSize: 54, fontWeight: 800, letterSpacing: 0.5, lineHeight: 1.15}}>{title}</div>
    </div>
  );
};

// ---------------- intro ----------------
const Intro: React.FC<Ctx & {s: Extract<Scene, {type: 'intro'}>}> = ({p, s}) => {
  const a = useEnter(0);
  return (
    <Area style={{justifyContent: 'center'}}>
      <div style={{...slideUp(a, 30)}}>
        <div style={{fontSize: 30, color: C.accent, fontWeight: 700, letterSpacing: 3}}>{p.sessionLabel}</div>
        <div style={{fontSize: 96, fontWeight: 800, margin: '8px 0 18px'}}>{p.dateLabel}</div>
        <div style={{fontSize: 40, color: C.sub, fontWeight: 500, maxWidth: 1500, lineHeight: 1.35}}>{s.data.theme || s.title}</div>
      </div>
      <div style={{display: 'flex', gap: 28, marginTop: 56}}>
        {s.data.hooks.map((h, i) => <HookCard key={i} n={i + 1} text={h} delay={20 + i * 14} />)}
      </div>
    </Area>
  );
};

const HookCard: React.FC<{n: number; text: string; delay: number}> = ({n, text, delay}) => {
  const e = useEnter(delay);
  return (
    <div style={{...panelStyle, flex: 1, padding: '26px 30px', ...slideUp(e, 50)}}>
      <div style={{fontSize: 22, fontWeight: 800, color: C.accent, marginBottom: 10}}>0{n}</div>
      <div style={{fontSize: 32, fontWeight: 600, lineHeight: 1.35}}>{text}</div>
    </div>
  );
};

// ---------------- market board ----------------
const Market: React.FC<Ctx & {s: Extract<Scene, {type: 'market'}>}> = ({p, s}) => (
  <Area>
    <SceneTitle title={s.title} kicker={p.labels.market} />
    <div style={{display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 20}}>
      {s.data.rows.map((r, i) => <MarketCard key={r.symbol} r={r} delay={6 + i * 4} colors={p.colors} />)}
    </div>
    {s.bullets.length ? (
      <div style={{marginTop: 30}}><Bullets items={s.bullets} delay={50} size={30} /></div>
    ) : null}
  </Area>
);

const MarketCard: React.FC<{r: Extract<Scene, {type: 'market'}>['data']['rows'][number]; delay: number; colors: Colors}> = ({r, delay, colors}) => {
  const e = useEnter(delay);
  const t = useT();
  const col = toneColor(r.change_pct, colors);
  const shown = r.change_pct * progress(t, delay, 30);
  return (
    <div style={{...panelStyle, padding: '18px 22px', ...slideUp(e, 30)}}>
      <div style={{fontSize: 24, color: C.sub, fontWeight: 600}}>{r.label}</div>
      <div style={{fontSize: 36, fontWeight: 700, marginTop: 4, fontVariantNumeric: 'tabular-nums'}}>{fmtValue(r.close, r.unit)}</div>
      <div style={{fontSize: 30, fontWeight: 800, color: col, fontVariantNumeric: 'tabular-nums'}}>{fmtPct(shown)}</div>
      <div style={{marginTop: 8}}><Sparkline data={r.spark} width={290} height={64} color={col} delay={delay + 6} /></div>
    </div>
  );
};

// ---------------- sectors ----------------
const Sectors: React.FC<Ctx & {s: Extract<Scene, {type: 'sectors'}>}> = ({p, s}) => {
  const t = useT();
  const rows = [...s.data.rows].sort((a, b) => b.change_pct - a.change_pct);
  const maxAbs = Math.max(0.5, ...rows.map((r) => Math.abs(r.change_pct)));
  const half = 400;
  return (
    <Area style={{flexDirection: 'row', gap: 48}}>
      <div style={{flex: 1.35}}>
        <SceneTitle title={s.title} kicker={p.labels.sectors} />
        <div style={{display: 'flex', flexDirection: 'column', gap: 10}}>
          {rows.map((r, i) => {
            const g = progress(t, 8 + i * 3, 30);
            const w = (Math.abs(r.change_pct) / maxAbs) * half * g;
            const col = toneColor(r.change_pct, p.colors);
            return (
              <div key={r.symbol} style={{display: 'flex', alignItems: 'center', height: 50, fontSize: 30, opacity: Math.min(1, g * 2)}}>
                <div style={{width: 190, color: C.sub, fontWeight: 600}}>{r.label}</div>
                <div style={{width: half * 2, position: 'relative', height: 36}}>
                  <div style={{position: 'absolute', left: half, top: -6, bottom: -6, width: 2, background: C.panelBorder}} />
                  <div style={{position: 'absolute', top: 0, height: 36, borderRadius: 6, background: col,
                    left: r.change_pct >= 0 ? half : half - w, width: w}} />
                </div>
                <div style={{width: 150, textAlign: 'right', color: col, fontWeight: 800, fontVariantNumeric: 'tabular-nums'}}>{fmtPct(r.change_pct)}</div>
              </div>
            );
          })}
        </div>
      </div>
      <div style={{flex: 0.65, paddingTop: 110}}>
        {s.bullets.length ? <Panel title={p.labels.keypoints} delay={30}><Bullets items={s.bullets} delay={40} size={30} /></Panel> : null}
      </div>
    </Area>
  );
};

// ---------------- movers ----------------
const Movers: React.FC<Ctx & {s: Extract<Scene, {type: 'movers'}>}> = ({p, s}) => (
  <Area>
    <SceneTitle title={s.title} kicker={p.labels.movers} />
    <div style={{display: 'flex', gap: 36}}>
      <MoverList title={p.labels.gainers} rows={s.data.gainers} colors={p.colors} delay={8} labels={p.labels} />
      <MoverList title={p.labels.losers} rows={s.data.losers} colors={p.colors} delay={20} labels={p.labels} />
    </div>
  </Area>
);

const MoverList: React.FC<{title: string; rows: Extract<Scene, {type: 'movers'}>['data']['gainers']; colors: Colors; delay: number; labels: Record<string, string>}> = ({title, rows, colors, delay, labels}) => {
  const t = useT();
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.change_pct)));
  return (
    <Panel title={title} delay={delay} style={{flex: 1}}>
      {rows.map((r, i) => {
        const g = progress(t, delay + 6 + i * 4, 28);
        const col = toneColor(r.change_pct, colors);
        return (
          <div key={r.symbol} style={{display: 'flex', alignItems: 'center', gap: 18, height: 74, borderTop: i ? `1px solid ${C.panelBorder}` : 'none', opacity: Math.min(1, g * 2)}}>
            <div style={{width: 120}}>
              <div style={{fontSize: 30, fontWeight: 800}}>{r.symbol}</div>
              <div style={{fontSize: 17, color: C.faint, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', width: 150}}>{r.name}</div>
            </div>
            <div style={{flex: 1, height: 18, background: 'rgba(255,255,255,0.05)', borderRadius: 9}}>
              <div style={{width: `${(Math.abs(r.change_pct) / maxAbs) * 100 * g}%`, height: '100%', borderRadius: 9, background: col}} />
            </div>
            <div style={{width: 140, textAlign: 'right', fontSize: 32, fontWeight: 800, color: col, fontVariantNumeric: 'tabular-nums'}}>{fmtPct(r.change_pct)}</div>
            <div style={{width: 120, textAlign: 'right', fontSize: 20, color: C.sub}}>{r.volume_ratio ? `${labels.vol} ${r.volume_ratio.toFixed(1)}x` : ''}</div>
          </div>
        );
      })}
    </Panel>
  );
};

// ---------------- story ----------------
const Story: React.FC<Ctx & {s: Extract<Scene, {type: 'story'}>; index: number}> = ({p, s, index}) => {
  const d = s.data;
  const col = toneColor(d.change_pct, p.colors);
  const head = useEnter(0);
  const D = s.durationInFrames;
  return (
    <Area style={{flexDirection: 'row', gap: 36}}>
      <div style={{flex: 1.45, display: 'flex', flexDirection: 'column'}}>
        <div style={{display: 'flex', alignItems: 'flex-end', gap: 26, marginBottom: 6, ...slideUp(head, 24)}}>
          <div style={{fontSize: 22, fontWeight: 800, color: C.accent, letterSpacing: 2, paddingBottom: 14}}>{p.labels.story} {index}</div>
          <div style={{fontSize: 76, fontWeight: 800, lineHeight: 1}}>{d.symbol}</div>
          <div style={{fontSize: 30, color: C.sub, paddingBottom: 8, maxWidth: 520, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{d.name}</div>
        </div>
        <div style={{display: 'flex', alignItems: 'baseline', gap: 24, marginBottom: 14, ...slideUp(head, 24)}}>
          <div style={{fontSize: 46, fontWeight: 700, fontVariantNumeric: 'tabular-nums'}}>${fmtPrice(d.close)}</div>
          <div style={{fontSize: 46, fontWeight: 800, color: col, fontVariantNumeric: 'tabular-nums'}}>{fmtPct(d.change_pct)}</div>
          <div style={{fontSize: 28, color: col}}>{d.change_abs >= 0 ? '+' : '−'}{fmtPrice(Math.abs(d.change_abs))}</div>
        </div>
        <div style={{fontSize: 34, fontWeight: 700, marginBottom: 12, ...slideUp(useEnter(10), 20)}}>{s.title}</div>
        <div style={{...panelStyle, padding: '18px 18px 10px', flex: 1}}>
          <CandleChart data={d.candles} width={1000} height={420} colors={p.colors} delay={12} />
        </div>
        <div style={{display: 'flex', gap: 14, marginTop: 16}}>
          {d.stats.slice(0, 5).map((st, i) => <StatChip key={i} {...st} colors={p.colors} delay={30 + i * 5} />)}
        </div>
      </div>
      <div style={{flex: 0.85, display: 'flex', flexDirection: 'column', gap: 18}}>
        {s.bullets.length ? <Panel title={p.labels.keypoints} delay={18}><Bullets items={s.bullets} delay={24} size={27} stagger={Math.round(D * 0.12)} /></Panel> : null}
        {d.sentiment ? (
          <Panel title={p.labels.sentiment} delay={Math.round(D * 0.35)}>
            <div style={{display: 'flex', gap: 20, alignItems: 'center'}}>
              <Gauge value={d.sentiment.score} size={200} colors={p.colors} delay={Math.round(D * 0.35) + 6} />
              <div style={{flex: 1, fontSize: 22, lineHeight: 1.4, display: 'flex', flexDirection: 'column', gap: 10}}>
                <div><span style={{color: p.colors.up, fontWeight: 800}}>▲ </span>{d.sentiment.bull}</div>
                <div><span style={{color: p.colors.down, fontWeight: 800}}>▼ </span>{d.sentiment.bear}</div>
                <div style={{color: C.faint, fontSize: 18}}>Stocktwits {p.labels.bull} {d.sentiment.bullish} · {p.labels.bear} {d.sentiment.bearish}</div>
              </div>
            </div>
          </Panel>
        ) : null}
        {d.headlines.length ? (
          <Panel title={p.labels.headlines} delay={Math.round(D * 0.6)}>
            {d.headlines.slice(0, 3).map((h, i) => (
              <div key={i} style={{fontSize: 21, lineHeight: 1.35, marginBottom: 12, display: 'flex', gap: 10}}>
                <span style={{color: C.accent, fontWeight: 700, whiteSpace: 'nowrap'}}>{h.source}</span>
                <span style={{color: C.text, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden'}}>{h.title}</span>
              </div>
            ))}
          </Panel>
        ) : null}
      </div>
    </Area>
  );
};

const StatChip: React.FC<{label: string; value: string; tone?: 'up' | 'down' | 'neutral'; colors: Colors; delay: number}> = ({label, value, tone, colors, delay}) => {
  const e = useEnter(delay);
  const col = tone === 'up' ? colors.up : tone === 'down' ? colors.down : C.text;
  return (
    <div style={{...panelStyle, flex: 1, padding: '12px 16px', borderRadius: 14, ...slideUp(e, 16)}}>
      <div style={{fontSize: 17, color: C.sub, whiteSpace: 'nowrap'}}>{label}</div>
      <div style={{fontSize: 27, fontWeight: 800, color: col, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap'}}>{value}</div>
    </div>
  );
};

// ---------------- crypto ----------------
const Crypto: React.FC<Ctx & {s: Extract<Scene, {type: 'crypto'}>}> = ({p, s}) => {
  const d = s.data;
  const btc = d.assets.find((a) => a.symbol === 'BTC');
  return (
    <Area style={{flexDirection: 'row', gap: 36}}>
      <div style={{flex: 1.3, display: 'flex', flexDirection: 'column'}}>
        <SceneTitle title={s.title} kicker={p.labels.crypto} />
        <Panel title={`BTC · 90D`} delay={6} style={{flex: 1}}>
          {btc ? (
            <div style={{display: 'flex', gap: 22, alignItems: 'baseline', marginBottom: 6}}>
              <div style={{fontSize: 48, fontWeight: 800, fontVariantNumeric: 'tabular-nums'}}>${fmtPrice(btc.price)}</div>
              <div style={{fontSize: 34, fontWeight: 800, color: toneColor(btc.change_pct, p.colors)}}>{fmtPct(btc.change_pct)} <span style={{fontSize: 20, color: C.sub}}>24h</span></div>
            </div>
          ) : null}
          <AreaChart data={d.btcHistory} width={1000} height={380} color={C.gold} delay={12} />
        </Panel>
      </div>
      <div style={{flex: 0.8, display: 'flex', flexDirection: 'column', gap: 18, paddingTop: 20}}>
        <Panel title={p.labels.prices} delay={14}>
          <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', rowGap: 14, columnGap: 18}}>
            {d.assets.filter((a) => a.symbol !== 'BTC').map((a) => (
              <div key={a.symbol} style={{display: 'flex', justifyContent: 'space-between', fontSize: 25}}>
                <span style={{fontWeight: 800}}>{a.symbol}</span>
                <span style={{color: toneColor(a.change_pct, p.colors), fontWeight: 700, fontVariantNumeric: 'tabular-nums'}}>{fmtPct(a.change_pct)}</span>
              </div>
            ))}
          </div>
        </Panel>
        {d.fearGreed ? (
          <Panel title={p.labels.feargreed} delay={30}>
            <div style={{display: 'flex', alignItems: 'center', gap: 20}}>
              <Gauge value={d.fearGreed.value} size={210} colors={p.colors} delay={36} />
              <div style={{fontSize: 24, lineHeight: 1.6}}>
                <div style={{fontWeight: 800, fontSize: 30}}>{d.fearGreed.label}</div>
                {d.fearGreed.week_ago !== null ? <div style={{color: C.sub}}>{p.labels.weekago}: {d.fearGreed.week_ago}</div> : null}
                {d.dominance ? <div style={{color: C.sub}}>{p.labels.dominance}: {d.dominance.toFixed(1)}%</div> : null}
              </div>
            </div>
          </Panel>
        ) : null}
        {d.funding.length ? (
          <Panel title={p.labels.funding} delay={46}>
            <div style={{display: 'flex', justifyContent: 'space-between', fontSize: 25}}>
              {d.funding.map((f) => (
                <div key={f.symbol}><span style={{fontWeight: 800}}>{f.symbol} </span>
                  <span style={{color: toneColor(f.rate_pct, p.colors), fontVariantNumeric: 'tabular-nums'}}>{f.rate_pct.toFixed(4)}%</span></div>
              ))}
            </div>
          </Panel>
        ) : null}
      </div>
    </Area>
  );
};

// ---------------- earnings (after hours / pre-market) ----------------
const Earnings: React.FC<Ctx & {s: Extract<Scene, {type: 'earnings'}>}> = ({p, s}) => {
  const t = useT();
  const rows = s.data.rows;
  const maxAbs = Math.max(2, ...rows.map((r) => Math.abs(r.move_pct ?? 0)));
  const eps = (v: number | null) => (v === null ? '—' : `$${v.toFixed(2)}`);
  return (
    <Area style={{flexDirection: 'row', gap: 36}}>
      <div style={{flex: 1.6, display: 'flex', flexDirection: 'column'}}>
        <SceneTitle title={s.title} kicker={p.labels.ah} />
        <Panel delay={6} style={{padding: '10px 28px'}}>
          <div style={{display: 'flex', gap: 18, height: 44, alignItems: 'center', fontSize: 19, color: C.faint, fontWeight: 600}}>
            <div style={{width: 300}} />
            <div style={{width: 250}}>{p.labels.eps} · {p.labels.est}</div>
            <div style={{width: 150, textAlign: 'right'}}>{p.labels.surprise}</div>
            <div style={{flex: 1, textAlign: 'right'}}>{s.data.moveLabel}</div>
          </div>
          {rows.map((r, i) => {
            const g = progress(t, 10 + i * 5, 28);
            const col = r.move_pct === null ? C.sub : toneColor(r.move_pct, p.colors);
            const sCol = r.surprise_pct === null ? C.sub : toneColor(r.surprise_pct, p.colors);
            return (
              <div key={r.symbol} style={{display: 'flex', alignItems: 'center', gap: 18, height: 88, borderTop: `1px solid ${C.panelBorder}`, opacity: Math.min(1, g * 2)}}>
                <div style={{width: 300}}>
                  <div style={{fontSize: 34, fontWeight: 800}}>{r.symbol}</div>
                  <div style={{fontSize: 19, color: C.faint, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{r.name}</div>
                </div>
                <div style={{width: 250, fontSize: 28, fontVariantNumeric: 'tabular-nums'}}>
                  <span style={{fontWeight: 800}}>{eps(r.eps)}</span>
                  <span style={{color: C.sub, fontSize: 22}}> / {eps(r.eps_est)}</span>
                </div>
                <div style={{width: 150, textAlign: 'right', fontSize: 28, fontWeight: 700, color: sCol, fontVariantNumeric: 'tabular-nums'}}>
                  {r.surprise_pct === null ? '—' : fmtPct(r.surprise_pct, 1)}
                </div>
                <div style={{flex: 1, display: 'flex', alignItems: 'center', gap: 16, justifyContent: 'flex-end'}}>
                  {r.move_pct !== null ? (
                    <>
                      <div style={{width: 200, height: 16, background: 'rgba(255,255,255,0.05)', borderRadius: 8}}>
                        <div style={{width: `${(Math.abs(r.move_pct) / maxAbs) * 100 * g}%`, height: '100%', borderRadius: 8, background: col}} />
                      </div>
                      <div style={{width: 140, textAlign: 'right', fontSize: 34, fontWeight: 800, color: col, fontVariantNumeric: 'tabular-nums'}}>{fmtPct(r.move_pct)}</div>
                    </>
                  ) : <div style={{fontSize: 22, color: C.faint}}>{p.labels.noquote}</div>}
                </div>
              </div>
            );
          })}
        </Panel>
      </div>
      {s.bullets.length ? (
        <div style={{flex: 0.6, paddingTop: 110}}>
          <Panel title={p.labels.keypoints} delay={30}><Bullets items={s.bullets} delay={40} size={27} /></Panel>
        </div>
      ) : null}
    </Area>
  );
};

// ---------------- calendar ----------------
const Calendar: React.FC<Ctx & {s: Extract<Scene, {type: 'calendar'}>}> = ({p, s}) => (
  <Area>
    <SceneTitle title={s.title} kicker={p.labels.calendar} />
    <div style={{display: 'flex', gap: 36}}>
      <Panel title={p.labels.earnings} delay={8} style={{flex: 1.1}}>
        {s.data.earnings.slice(0, 9).map((e, i) => (
          <Row key={i} delay={14 + i * 3} cells={[e.date.slice(5), e.symbol, e.name, e.time]} widths={[90, 110, 0, 70]} />
        ))}
        {!s.data.earnings.length ? <div style={{color: C.sub, fontSize: 24}}>—</div> : null}
      </Panel>
      <Panel title={p.labels.macro} delay={18} style={{flex: 1}}>
        {s.data.macro.slice(0, 8).map((e, i) => (
          <Row key={i} delay={24 + i * 3} cells={[e.date.slice(5), e.time, e.event, e.impact]} widths={[80, e.timeSub ? 250 : 90, 0, 70]}
            sub={e.timeSub ? {1: e.timeSub} : undefined} accent={e.impact === 'High' || e.impact === '高' ? C.gold : undefined} />
        ))}
        {!s.data.macro.length ? <div style={{color: C.sub, fontSize: 24}}>—</div> : null}
      </Panel>
    </div>
  </Area>
);

// `sub` puts a small second line under a cell (e.g. Los Angeles / Beijing time under the New York time).
const Row: React.FC<{cells: string[]; widths: number[]; delay: number; accent?: string; sub?: Record<number, string>}> = ({cells, widths, delay, accent, sub}) => {
  const e = useEnter(delay);
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 14, height: sub ? 66 : 56, fontSize: 24, borderBottom: `1px solid ${C.panelBorder}`, ...slideUp(e, 12)}}>
      {cells.map((c, i) => (
        <div key={i} style={{width: widths[i] || undefined, flex: widths[i] ? undefined : 1, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis',
          color: i === 1 ? C.text : i === cells.length - 1 ? (accent || C.sub) : i === 0 ? C.accent : C.text, fontWeight: i === 1 ? 800 : 500}}>
          {c}
          {sub?.[i] ? <div style={{fontSize: 16, color: C.faint, fontWeight: 500, marginTop: 2}}>{sub[i]}</div> : null}
        </div>
      ))}
    </div>
  );
};

// ---------------- outro ----------------
const Outro: React.FC<Ctx & {s: Extract<Scene, {type: 'outro'}>}> = ({p, s}) => {
  const a = useEnter(0);
  const b = useEnter(16);
  return (
    <Area style={{justifyContent: 'center', alignItems: 'center', textAlign: 'center'}}>
      <div style={{...slideUp(a, 30)}}>
        <div style={{fontSize: 30, color: C.accent, fontWeight: 700, letterSpacing: 3}}>{s.title}</div>
        <div style={{fontSize: 52, fontWeight: 800, maxWidth: 1500, lineHeight: 1.3, margin: '18px auto 40px'}}>{s.data.theme}</div>
      </div>
      <div style={{...slideUp(b, 30)}}>
        <div style={{display: 'inline-block', padding: '16px 40px', borderRadius: 40, fontSize: 30, fontWeight: 700,
          background: `linear-gradient(135deg, ${C.accent}, ${C.accent2})`}}>{s.data.cta}</div>
        <div style={{fontSize: 22, color: C.faint, marginTop: 40, maxWidth: 1300, lineHeight: 1.5}}>{s.data.disclaimer}</div>
      </div>
    </Area>
  );
};

export const SceneView: React.FC<{p: BriefingProps; s: Scene}> = ({p, s}) => {
  switch (s.type) {
    case 'intro': return <Intro p={p} s={s} />;
    case 'market': return <Market p={p} s={s} />;
    case 'sectors': return <Sectors p={p} s={s} />;
    case 'movers': return <Movers p={p} s={s} />;
    case 'story': return <Story p={p} s={s} index={Number(s.id.replace('story', '')) || 1} />;
    case 'crypto': return <Crypto p={p} s={s} />;
    case 'earnings': return <Earnings p={p} s={s} />;
    case 'calendar': return <Calendar p={p} s={s} />;
    case 'outro': return <Outro p={p} s={s} />;
  }
};
