export const fmtPct = (x: number | null | undefined, digits = 2): string => {
  if (x === null || x === undefined || Number.isNaN(x)) return '—';
  const s = Math.abs(x).toFixed(digits);
  return `${x >= 0 ? '+' : '−'}${s}%`;
};

export const fmtPrice = (x: number | null | undefined): string => {
  if (x === null || x === undefined || Number.isNaN(x)) return '—';
  const abs = Math.abs(x);
  const digits = abs >= 10000 ? 0 : abs >= 1000 ? 1 : abs >= 1 ? 2 : 4;
  return x.toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits});
};

export const fmtValue = (x: number, unit: 'price' | 'yield'): string =>
  unit === 'yield' ? `${x.toFixed(3)}%` : fmtPrice(x);

export const toneColor = (x: number, colors: {up: string; down: string}, neutral = '#8b97ad'): string =>
  x > 0 ? colors.up : x < 0 ? colors.down : neutral;
