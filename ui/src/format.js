// Number and date formatting, in one place so the same value never renders two
// ways on two charts.

const COMPACT = new Intl.NumberFormat('en-GB', {
  notation: 'compact',
  maximumFractionDigits: 1,
});
const PLAIN = new Intl.NumberFormat('en-GB');

export function count(n) {
  return n == null ? '—' : PLAIN.format(n);
}

/** Axis ticks and dense labels: "€12.4M". */
export function moneyCompact(n) {
  return n == null ? '—' : `€${COMPACT.format(n)}`;
}

/** Tooltips and tables, where the exact figure is the point. */
export function money(n) {
  if (n == null) return '—';
  return `€${PLAIN.format(Math.round(n))}`;
}

export function date(iso) {
  return iso || '—';
}

/** Truncate for a table cell without hiding that it was truncated. */
export function truncate(text, max = 90) {
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}
