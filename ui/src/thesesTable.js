// Pure sort/filter helpers for the "All N theses" table in Theses.jsx — kept
// free of React and fetch so they can be unit-tested without a DOM.

/** The sentinel group code for a thesis whose two attribution signals
 *  resolved to nothing — same value Theses.jsx's own groups-breakdown table
 *  already uses for its "Unattributed" row, imported from here so the two
 *  features cannot drift apart on the string. */
export const UNATTRIBUTED = 'UNATTRIBUTED';

/** The group codes GroupChips itself renders for a thesis: the ranked
 *  people+content attribution where it exists, falling back to the plain
 *  `groups` list for an older payload — same fallback GroupChips uses
 *  (Theses.jsx), kept in sync here deliberately rather than re-derived
 *  differently. Ranked order matters: index 0 is the people-signal
 *  candidate, which is what both the group filter and the group sort key
 *  below treat as "the" group for a contested thesis. */
export function rankedGroupCodes(t) {
  const ranked = t.group_attribution?.ranked?.length
    ? t.group_attribution.ranked
    : t.groups.map((code) => ({ code }));
  return ranked.map((r) => r.code);
}

/** One author/supervisor's dedup key — the same tiebreak Overview.jsx's
 *  studentKey uses: a resolved person keys on their slug (so the same
 *  student across theses collapses to one option), an unresolved name
 *  keys on itself. */
export function personKey(p) {
  return p.matched.length ? `slug:${p.matched[0].slug}` : `name:${p.name}`;
}

const collate = (a, b) => (a || '').localeCompare(b || '', undefined, { sensitivity: 'base' });

function dirSign(dir) {
  return dir === 'desc' ? -1 : 1;
}

/** Orders by `compare(aVal, bVal)`, but a missing value (null/undefined)
 *  always sorts last — independent of `dir` — so reversing the column never
 *  makes absent data jump to the top. Only the non-missing branch flips
 *  with direction; the missing branch is unconditional. */
function compareMissingLast(aVal, bVal, compare, dir) {
  const aMissing = aVal == null;
  const bMissing = bVal == null;
  if (aMissing && bMissing) return 0;
  if (aMissing) return 1;
  if (bMissing) return -1;
  return dirSign(dir) * compare(aVal, bVal);
}

// Each entry is a fully dir-aware comparator (a, b, dir) -> number. Missing
// data (no author, no year, no resolved group) sorts last in both
// directions; everything else flips with `dir`.
const COMPARATORS = {
  title: (a, b, dir) => dirSign(dir) * collate(a.title, b.title),
  author: (a, b, dir) => compareMissingLast(a.authors[0]?.name, b.authors[0]?.name, collate, dir),
  supervisors: (a, b, dir) =>
    compareMissingLast(a.supervisors[0]?.name, b.supervisors[0]?.name, collate, dir),
  year: (a, b, dir) => compareMissingLast(a.year, b.year, (x, y) => x - y, dir),
  group: (a, b, dir) =>
    compareMissingLast(rankedGroupCodes(a)[0], rankedGroupCodes(b)[0], collate, dir),
  // Boolean, not missing-able: "Indexed" first on asc.
  full_text: (a, b, dir) => dirSign(dir) * (Number(b.full_text) - Number(a.full_text)),
};

/** Sorts a COPY of `theses` by `key` (one of COMPARATORS' keys); `dir` is
 *  'asc' | 'desc' | falsy (falsy = original API order, still a fresh copy
 *  so the caller never mutates the source array). */
export function sortTheses(theses, { key, dir } = {}) {
  if (!key || !dir || !COMPARATORS[key]) return [...theses];
  const compare = COMPARATORS[key];
  return [...theses].sort((a, b) => compare(a, b, dir));
}

/** `groups`: a Set of codes (plus possibly UNATTRIBUTED) — OR within the
 *  set, a thesis matches if ANY of its displayed ranked codes is selected,
 *  or if it has none and UNATTRIBUTED is selected (a contested thesis with
 *  two displayed groups matches either).
 *  `authorKeys`: a Set of personKey()s — OR within the set, AND against the
 *  group filter. Either Set empty/undefined means "no constraint". */
export function filterTheses(theses, { groups, authorKeys } = {}) {
  const hasGroupFilter = groups && groups.size > 0;
  const hasAuthorFilter = authorKeys && authorKeys.size > 0;
  if (!hasGroupFilter && !hasAuthorFilter) return theses;
  return theses.filter((t) => {
    if (hasGroupFilter) {
      const codes = rankedGroupCodes(t);
      const matchesGroup = codes.length
        ? codes.some((c) => groups.has(c))
        : groups.has(UNATTRIBUTED);
      if (!matchesGroup) return false;
    }
    if (hasAuthorFilter && !t.authors.some((p) => authorKeys.has(personKey(p)))) {
      return false;
    }
    return true;
  });
}
