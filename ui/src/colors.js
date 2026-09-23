// Colour follows the entity, never its rank.
//
// Every chart that splits by research group reads its colour from this fixed
// map, keyed by the group's own code. Endpoints sort their rows differently
// (projects_per_group by count, budget_by_group by budget sum), and a filter
// can drop a group entirely — if colour came from array position, CMS would be
// blue on one chart and orange on the next, and hiding a group would repaint
// the survivors. The six slots are the `dataviz` reference palette's first
// six, in its own validated order; see theme.css for the validator results.
//
// A slot is named, not hex-valued, because the two places it gets used want
// different things:
//
//   SVG marks  -> a CLASS NAME. `fill="var(--series-1)"` does not work: SVG
//                 presentation ATTRIBUTES do not resolve custom properties,
//                 only CSS properties do. Recharts sets fill as an attribute,
//                 so the mark renders with no paint at all — invisible, no
//                 error. (Cost us one round of "why are the bar labels
//                 missing".) A class lets the stylesheet set `fill` as a real
//                 CSS property, which resolves the var fine.
//   HTML chrome -> the custom property itself, in a `background`.
//
// The upside of routing everything through CSS: switching theme repaints every
// chart with no React re-render, because nothing holds a resolved hex.

export const GROUP_ORDER = ['AC', 'bAI', 'CMS', 'IS', 'NCS', 'SSE'];

const SLOT_BY_GROUP = {
  AC: 'series-1',
  bAI: 'series-2',
  CMS: 'series-3',
  IS: 'series-4',
  NCS: 'series-5',
  SSE: 'series-6',
};

/** The one-hue sequential slot, for charts that encode magnitude only. */
export const SEQUENTIAL = 'sequential';

/** Slot name for a group. A group the map has never seen (the site adding a
 *  seventh) gets the muted ink rather than a generated hue — an unvalidated
 *  colour is worse than a grey one, and it is visibly "not one of the six". */
export function groupSlot(code) {
  return SLOT_BY_GROUP[code] || 'muted';
}

/** Class that paints an SVG mark for a slot (see theme.css). */
export function fillClass(slot) {
  return `viz-fill-${slot}`;
}

/** CSS custom property for a slot, for HTML swatches and borders. */
export function slotVar(slot) {
  if (slot === 'sequential') return 'var(--sequential-400)';
  if (slot === 'muted') return 'var(--text-muted)';
  return `var(--${slot})`;
}

/** Shorthand: the HTML swatch colour for a research group. */
export function groupColorVar(code) {
  return slotVar(groupSlot(code));
}

/** Partner classification (project_partners.partner_type) — two fixed
 *  slots, same "colour follows the entity, never its rank" rule as
 *  research groups above, so academic stays one colour and industry
 *  another everywhere a partner is drawn (the Partners view, a project's
 *  detail page, ...). */
const SLOT_BY_PARTNER_TYPE = {
  academic: 'series-1',
  industry: 'series-2',
};

export function partnerTypeSlot(type) {
  return SLOT_BY_PARTNER_TYPE[type] || 'muted';
}

export function partnerTypeColorVar(type) {
  return slotVar(partnerTypeSlot(type));
}
