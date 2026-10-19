// Props contract between the Python pipeline (infostation.media.render) and the Remotion templates.
// Python precomputes every number; templates only lay out and animate.

export type Lang = 'zh' | 'en';

export type Caption = {start: number; end: number; text: string};

export type MarketRow = {
  symbol: string;
  label: string;
  close: number;
  change_pct: number;
  unit: 'price' | 'yield';
  spark: number[];
};

export type Candle = {date: string; open: number; high: number; low: number; close: number; volume: number};

export type Mover = {symbol: string; name: string; change_pct: number; close: number; volume_ratio: number | null};

export type StoryData = {
  symbol: string;
  name: string;
  close: number;
  change_pct: number;
  change_abs: number;
  stats: {label: string; value: string; tone?: 'up' | 'down' | 'neutral'}[];
  candles: Candle[];
  sentiment: {score: number; bull: string; bear: string; bullish: number; bearish: number} | null;
  headlines: {title: string; source: string}[];
};

export type CryptoData = {
  assets: {symbol: string; price: number; change_pct: number}[];
  funding: {symbol: string; rate_pct: number}[];
  fearGreed: {value: number; label: string; week_ago: number | null} | null;
  dominance: number | null;
  totalMcapT: number | null;
  btcHistory: {date: string; close: number}[];
};

export type CalendarData = {
  earnings: {date: string; symbol: string; name: string; time: string}[];
  macro: {date: string; time: string; timeSub?: string; event: string; impact: string}[];
};

export type EarningsData = {
  moveLabel: string;
  rows: {symbol: string; name: string; eps: number | null; eps_est: number | null; surprise_pct: number | null; move_pct: number | null}[];
};

export type SceneBase = {
  id: string;
  title: string;
  bullets: string[];
  chapter: string;
  audio: string | null;
  durationInFrames: number;
  captions: Caption[];
};

export type Scene =
  | (SceneBase & {type: 'intro'; data: {theme: string; hooks: string[]}})
  | (SceneBase & {type: 'market'; data: {rows: MarketRow[]}})
  | (SceneBase & {type: 'sectors'; data: {rows: {symbol: string; label: string; change_pct: number; change_5d_pct: number | null}[]}})
  | (SceneBase & {type: 'movers'; data: {gainers: Mover[]; losers: Mover[]}})
  | (SceneBase & {type: 'story'; data: StoryData})
  | (SceneBase & {type: 'crypto'; data: CryptoData})
  | (SceneBase & {type: 'earnings'; data: EarningsData})
  | (SceneBase & {type: 'calendar'; data: CalendarData})
  | (SceneBase & {type: 'outro'; data: {theme: string; disclaimer: string; cta: string}});

export type Labels = Record<string, string>;

export type BriefingProps = {
  lang: Lang;
  fps: number;
  width: number;
  height: number;
  brand: {name: string; handle: string};
  dateLabel: string;
  sessionLabel: string;
  colors: {up: string; down: string};
  labels: Labels;
  bgImage: string | null;
  bgm: string | null;
  bgmVolume: number;
  tape: {label: string; change_pct: number}[];
  scenes: Scene[];
  footnote?: string;            // cards only, e.g. "data as of …"
};

export type ThumbnailProps = {
  lang: Lang;
  text: string;
  subtext: string;
  brand: string;
  dateLabel: string;
  colors: {up: string; down: string};
  bgImage: string | null;
  badges: {label: string; change_pct: number}[];
  chart: number[];
};

export type CardProps = {
  briefing: BriefingProps;
  sceneId: string;
};
