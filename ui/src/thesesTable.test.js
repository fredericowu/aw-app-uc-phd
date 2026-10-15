import { describe, expect, it } from 'vitest';
import { UNATTRIBUTED, filterTheses, personKey, rankedGroupCodes, sortTheses } from './thesesTable';

function thesis(overrides) {
  return {
    handle: 'h',
    title: 'T',
    authors: [],
    supervisors: [],
    year: null,
    groups: [],
    full_text: false,
    ...overrides,
  };
}

function matchedAuthor(name, slug) {
  return { name, status: 'matched', matched: [{ slug }] };
}

function unmatchedAuthor(name) {
  return { name, status: 'unmatched', matched: [] };
}

describe('rankedGroupCodes', () => {
  it('prefers the ranked attribution over the plain groups list', () => {
    const t = thesis({
      groups: ['AC', 'IS'],
      group_attribution: { ranked: [{ code: 'IS' }, { code: 'AC' }] },
    });
    expect(rankedGroupCodes(t)).toEqual(['IS', 'AC']);
  });

  it('falls back to groups when there is no ranked attribution', () => {
    const t = thesis({ groups: ['CMS'] });
    expect(rankedGroupCodes(t)).toEqual(['CMS']);
  });

  it('is empty for an unattributed thesis', () => {
    expect(rankedGroupCodes(thesis({ groups: [] }))).toEqual([]);
  });
});

describe('personKey', () => {
  it('keys a resolved person on their slug', () => {
    expect(personKey(matchedAuthor('Author One', 'author-one'))).toBe('slug:author-one');
  });

  it('keys an unresolved person on their raw name', () => {
    expect(personKey(unmatchedAuthor('Author Two'))).toBe('name:Author Two');
  });
});

describe('filterTheses — groups', () => {
  const contested = thesis({
    handle: 'contested',
    groups: ['AC', 'IS'],
    group_attribution: { ranked: [{ code: 'AC' }, { code: 'IS' }] },
  });
  const unattributed = thesis({ handle: 'unattributed', groups: [] });
  const plain = thesis({ handle: 'plain', groups: ['CMS'] });
  const theses = [contested, unattributed, plain];

  it('matches a contested thesis on EITHER of its two displayed groups', () => {
    expect(filterTheses(theses, { groups: new Set(['IS']) }).map((t) => t.handle)).toEqual([
      'contested',
    ]);
    expect(filterTheses(theses, { groups: new Set(['AC']) }).map((t) => t.handle)).toEqual([
      'contested',
    ]);
  });

  it('matches unattributed theses only via the UNATTRIBUTED sentinel', () => {
    expect(filterTheses(theses, { groups: new Set([UNATTRIBUTED]) }).map((t) => t.handle)).toEqual([
      'unattributed',
    ]);
  });

  it('unions multiple selected groups', () => {
    expect(
      filterTheses(theses, { groups: new Set(['CMS', UNATTRIBUTED]) }).map((t) => t.handle),
    ).toEqual(['unattributed', 'plain']);
  });

  it('is a no-op with an empty set', () => {
    expect(filterTheses(theses, { groups: new Set() })).toBe(theses);
  });
});

describe('filterTheses — authors', () => {
  const a = thesis({ handle: 'a', authors: [matchedAuthor('João Silva', 'joao-silva')] });
  const b = thesis({ handle: 'b', authors: [unmatchedAuthor('Maria Costa')] });
  const c = thesis({ handle: 'c', authors: [matchedAuthor('Ana Reis', 'ana-reis')] });
  const theses = [a, b, c];

  it('matches on a resolved author key', () => {
    expect(
      filterTheses(theses, { authorKeys: new Set(['slug:joao-silva']) }).map((t) => t.handle),
    ).toEqual(['a']);
  });

  it('matches on an unresolved author key', () => {
    expect(
      filterTheses(theses, { authorKeys: new Set(['name:Maria Costa']) }).map((t) => t.handle),
    ).toEqual(['b']);
  });

  it('unions multiple selected authors', () => {
    expect(
      filterTheses(theses, {
        authorKeys: new Set(['slug:joao-silva', 'slug:ana-reis']),
      }).map((t) => t.handle),
    ).toEqual(['a', 'c']);
  });

  it('ANDs the author filter with the group filter', () => {
    const contestedAuthor = thesis({
      handle: 'd',
      authors: [matchedAuthor('João Silva', 'joao-silva')],
      groups: ['AC'],
    });
    const result = filterTheses([a, contestedAuthor], {
      groups: new Set(['AC']),
      authorKeys: new Set(['slug:joao-silva']),
    });
    expect(result.map((t) => t.handle)).toEqual(['d']);
  });
});

describe('sortTheses — year, missing always last', () => {
  const withYear2020 = thesis({ handle: '2020', year: 2020 });
  const withYear1999 = thesis({ handle: '1999', year: 1999 });
  const noYear = thesis({ handle: 'none', year: null });
  const theses = [withYear2020, noYear, withYear1999];

  it('puts the missing year last ascending', () => {
    expect(sortTheses(theses, { key: 'year', dir: 'asc' }).map((t) => t.handle)).toEqual([
      '1999',
      '2020',
      'none',
    ]);
  });

  it('puts the missing year last descending too', () => {
    expect(sortTheses(theses, { key: 'year', dir: 'desc' }).map((t) => t.handle)).toEqual([
      '2020',
      '1999',
      'none',
    ]);
  });

  it('with no dir, returns an unsorted COPY (never the same array reference)', () => {
    const copy = sortTheses(theses, {});
    expect(copy).toEqual(theses);
    expect(copy).not.toBe(theses);
  });
});

describe('sortTheses — group, first-ranked code, unattributed always last', () => {
  const groupA = thesis({ handle: 'a-first', groups: ['AC'] });
  const groupC = thesis({ handle: 'c-first', groups: ['CMS'] });
  const unattributed = thesis({ handle: 'unattributed', groups: [] });
  const contested = thesis({
    handle: 'contested-b-first',
    groups: ['CMS', 'bAI'],
    group_attribution: { ranked: [{ code: 'bAI' }, { code: 'CMS' }] },
  });
  const theses = [groupC, unattributed, groupA, contested];

  it('sorts by the FIRST ranked code, unattributed last both directions', () => {
    expect(sortTheses(theses, { key: 'group', dir: 'asc' }).map((t) => t.handle)).toEqual([
      'a-first',
      'contested-b-first',
      'c-first',
      'unattributed',
    ]);
    expect(sortTheses(theses, { key: 'group', dir: 'desc' }).map((t) => t.handle)).toEqual([
      'c-first',
      'contested-b-first',
      'a-first',
      'unattributed',
    ]);
  });
});

describe('sortTheses — title and full_text', () => {
  it('sorts titles accent-insensitively', () => {
    const theses = [thesis({ handle: 'z', title: 'Zebra' }), thesis({ handle: 'c', title: 'Conceição' })];
    expect(sortTheses(theses, { key: 'title', dir: 'asc' }).map((t) => t.handle)).toEqual(['c', 'z']);
  });

  it('puts Indexed first ascending, Metadata-only first descending', () => {
    const indexed = thesis({ handle: 'indexed', full_text: true });
    const metaOnly = thesis({ handle: 'meta', full_text: false });
    expect(
      sortTheses([metaOnly, indexed], { key: 'full_text', dir: 'asc' }).map((t) => t.handle),
    ).toEqual(['indexed', 'meta']);
    expect(
      sortTheses([metaOnly, indexed], { key: 'full_text', dir: 'desc' }).map((t) => t.handle),
    ).toEqual(['meta', 'indexed']);
  });
});
