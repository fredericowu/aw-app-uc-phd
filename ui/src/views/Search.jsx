// Semantic search over the thesis corpus (S6), consuming S3's /api/search.
// No index of our own — every hit is a chunk ranked by pgvector cosine
// distance. Three things the backend deliberately encodes that this view
// must not flatten away (see search.py / store.py docstrings):
//
//   1. `full_text: false` means the thesis is embargoed — only its title and
//      abstracts were indexed. Marked visibly, never presented like a
//      full-text hit.
//   2. A degraded store answers a typed 503, never `results: []` — rendered
//      as a diagnostic, kept apart from a genuine zero-match search.
//   3. `distance` is cosine distance (lower = closer) — never shown as a
//      percentage. Same decision as Fit (see api/fit.py / Fit.jsx): this
//      corpus scores in too narrow a band for a "Match 68%" to mean
//      anything, so a thesis found unrelated to the query ("quem descobriu
//      o brasil" surfacing an acknowledgments passage at "68%") reads as
//      confidently relevant instead of the weak, coincidental hit it is.
//      `distance` still drives ranking and the MIN_MATCH floor below; it is
//      just never rendered as a score — only each result's rank is.

import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../api';
import { AsyncBoundary, Caveat, ExternalLink, Section, useAsync } from '../components';
import { count } from '../format';

const K = 20;
const DEBOUNCE_MS = 350;
// A broad query can pull a dozen+ chunks from one long thesis, burying the
// other theses that matched — show the strongest few per thesis and let the
// rest stay one click away, rather than a wall of near-duplicate passages.
const PASSAGES_PREVIEW = 3;
// pgvector kNN always returns the k nearest chunks, however irrelevant —
// there is no backend-side "no match" the way a keyword search has one, so
// a nonsense query still comes back "matching" something. Observed on this
// corpus/model: a genuinely on-topic hit lands at match >= ~0.6, a
// nonsense-query hit in the mid-0.5s — this floor is what makes "nothing
// relevant" a reachable state instead of every query always matching.
const MIN_MATCH = 0.6;

const EXAMPLES = [
  'computational creativity',
  'federated learning for manufacturing',
  'aprendizagem de máquina',
  'segurança e privacidade de dados',
];

/** Cosine distance -> a 0-1 relevance score, bigger is closer. Used only to
 *  filter out weak hits (MIN_MATCH) and to order results — never displayed,
 *  per the no-percentage decision above. Clamped because an unrelated query
 *  can push distance past 1. */
function relevance(distance) {
  return Math.max(0, Math.min(1, 1 - distance));
}

/** Chunks arrive flat, best-first, and chunks from the same thesis rank
 *  adjacently — group them under one thesis card, in first-seen (i.e. best
 *  distance) order, so one document never reads as several. */
function groupByThesis(results) {
  const order = [];
  const byHandle = new Map();
  for (const r of results) {
    if (!byHandle.has(r.handle)) {
      byHandle.set(r.handle, {
        handle: r.handle,
        title: r.title,
        source_url: r.source_url,
        full_text: r.full_text,
        passages: [],
      });
      order.push(r.handle);
    }
    byHandle.get(r.handle).passages.push(r);
  }
  return order.map((h) => byHandle.get(h));
}

function ResultGroup({ group, rank, total }) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? group.passages : group.passages.slice(0, PASSAGES_PREVIEW);
  const hiddenCount = group.passages.length - shown.length;

  return (
    <div className="card search-result">
      <div className="search-result-head">
        <p className="chart-title">
          <span className="result-rank">#{rank}</span>{' '}
          <ExternalLink href={group.source_url}>{group.title}</ExternalLink>
        </p>
        {group.full_text ? null : (
          <span
            className="chip chip-warn"
            title="The full text of this thesis was not indexed — only its title and abstracts were searched."
          >
            Abstract only (embargoed)
          </span>
        )}
      </div>
      <p className="chart-note">
        Rank {rank} of {total} closest matches
      </p>
      <ul className="search-passages">
        {shown.map((p) => (
          <li key={`${p.handle}-${p.ordinal}`}>
            <p className="search-snippet">…{p.snippet}…</p>
          </li>
        ))}
      </ul>
      {hiddenCount > 0 ? (
        <button type="button" className="table-toggle" onClick={() => setExpanded(true)}>
          Show {hiddenCount} more {hiddenCount === 1 ? 'passage' : 'passages'} from this thesis
        </button>
      ) : null}
      {expanded && group.passages.length > PASSAGES_PREVIEW ? (
        <button type="button" className="table-toggle" onClick={() => setExpanded(false)}>
          Show fewer passages
        </button>
      ) : null}
    </div>
  );
}

function SearchDiagnostic({ error }) {
  const degraded = error instanceof ApiError && error.status === 503;
  return (
    <div className="card search-error" role="alert">
      <p className="chart-title search-error-title">
        {degraded ? 'Search is unavailable right now' : 'Search failed'}
      </p>
      <p className="chart-note">{error.message}</p>
      {degraded ? (
        <p className="chart-note">
          This is a backend problem, not a search with no matches — try again shortly.
        </p>
      ) : null}
    </div>
  );
}

export default function Search() {
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    const t = setTimeout(() => setQuery(input.trim()), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [input]);

  const searchState = useAsync(() => (query ? api.search(query, K) : Promise.resolve(null)), [query]);
  const thesesState = useAsync(() => api.theses(), []);

  const groups = useMemo(() => {
    if (!searchState.data) return [];
    const relevant = searchState.data.results.filter((r) => relevance(r.distance) >= MIN_MATCH);
    return groupByThesis(relevant);
  }, [searchState.data]);

  return (
    <Section
      title="Search"
      note="Semantic search over the full text and abstracts of every DEI doctoral thesis extracted from Estudo Geral. Ask a question in Portuguese or English — results are ranked by meaning, not keyword match."
    >
      <AsyncBoundary state={thesesState}>
        {(t) => {
          const total = t.theses.length;
          const embargoed = t.theses.filter((th) => !th.full_text).length;
          return (
            <Caveat label="What this searches">
              {count(total)} theses are indexed
              {embargoed
                ? `, ${count(embargoed)} of them abstract-only (embargoed — full text wasn't available, so only the title and abstracts were indexed)`
                : ''}
              . Abstract-only results are marked below rather than shown like a full-text hit.
            </Caveat>
          );
        }}
      </AsyncBoundary>

      <div className="filters">
        <input
          type="search"
          value={input}
          placeholder="Ask a question, in Portuguese or English…"
          aria-label="Search the theses"
          autoFocus
          onChange={(e) => setInput(e.target.value)}
        />
      </div>

      {!query ? (
        <div className="card search-empty">
          <p className="chart-note">Type a question above, or try one of these:</p>
          <div className="search-examples">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                className="group-pill"
                onClick={() => setInput(ex)}
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      ) : searchState.loading ? (
        <p className="state">Searching…</p>
      ) : searchState.error ? (
        <SearchDiagnostic error={searchState.error} />
      ) : !groups.length ? (
        <p className="state">
          No theses matched “{query}”. Semantic search still needs some overlap in meaning — try
          different words.
        </p>
      ) : (
        <>
          <p className="chart-note">
            {count(groups.length)} {groups.length === 1 ? 'thesis matches' : 'theses match'} “{query}”
            {searchState.data
              ? ` — embedded in ${searchState.data.embed_ms}ms, searched in ${searchState.data.db_ms}ms.`
              : ''}
          </p>
          <div className="search-results">
            {groups.map((g, i) => (
              <ResultGroup key={g.handle} group={g} rank={i + 1} total={groups.length} />
            ))}
          </div>
        </>
      )}
    </Section>
  );
}
