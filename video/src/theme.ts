import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import '@fontsource/inter/800.css';

export const FONT = "'Inter', 'Source Han Sans CN', 'Noto Sans CJK SC', 'Noto Sans SC', sans-serif";

export const C = {
  bg0: '#060a12',
  bg1: '#0c1322',
  panel: 'rgba(20, 30, 50, 0.72)',
  panelBorder: 'rgba(120, 160, 230, 0.16)',
  grid: 'rgba(120, 160, 230, 0.07)',
  text: '#eef3fb',
  sub: '#9aa9c2',
  faint: '#5d6b85',
  accent: '#4f8cff',
  accent2: '#a46bff',
  gold: '#f5b942',
  neutral: '#8b97ad',
};

export const panelStyle: React.CSSProperties = {
  background: C.panel,
  border: `1px solid ${C.panelBorder}`,
  borderRadius: 20,
  boxShadow: '0 10px 40px rgba(0,0,0,0.35)',
  backdropFilter: 'blur(6px)',
};

// Content area between the header and the caption band.
export const LAYOUT = {
  headerH: 104,
  top: 132,
  bottom: 860,
  side: 72,
};
