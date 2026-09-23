// Bibliography — every work cited anywhere in the thesis corpus, ranked by
// how many theses cite it, each expandable to the citing theses themselves.
//
// The default view is floored at 2 citing theses, and the reason is on screen
// rather than buried here: 22,609 of the 23,316 works are cited exactly once,
// so a "ranking" without a floor is 23,316 rows tied at 1 in alphabetical
// order. The distribution bar and the "Show all" pill exist so a reader can
// check that claim instead of taking it — same argument Collab.jsx makes for
// its own floor, and the same shape.

import { useEffect, useState } from 'react';
import { api } from '../api';
import { AsyncBoundary, Caveat, DataTable, Section, Tile, useAsync } from '../components';
import { count } from '../format';

const PAGE_SIZE = 50;
const FLOOR_OPTIONS = [1, 2, 3, 4, 5];
const TIER_LABEL = { doi: 'DOI (exact)', title: 'Title + author', unmatched: 'No key' };

function TierBadge({ tier }) {
  // A count of 3 at tier 'title' is a weaker claim than a count of 3 at tier
  // 'doi'. Showing the tier per row is the only way a reader can tell.
  return (
    <span className="legend-item" title={TIER_LABEL[tier] || tier}>
      {TIER_LABEL[tier] || tier}
    </span>
  );
}

function Distribution({ histogram }) {
  const entries = Object.entries(histogram).sort((a, b) => Number(a[0]) - Number(b[0]));
  const total = entries.reduce((sum, [, n]) => sum + n, 0);
  return (
    <div className="card">
      <p className="chart-note">
        How many works are cited by exactly N theses — the evidence for the default floor.
      </p>
      <DataTable
        columns={[
          { key: 'cited_by', label: 'Cited by N theses', numeric: true },
          { key: 'reference_count', label: 'Distinct works', numeric: true, render: (r) => count(r.reference_count) },
          {
            key: 'share',
            label: 'Share of corpus',
            numeric: true,
            render: (r) => `${((r.reference_count / total) * 100).toFixed(1)}%`,
          },
        ]}
        rows={entries.map(([cited_by, reference_count]) => ({
          cited_by: Number(cited_by),
          reference_count,
        }))}
        getKey={(r) => r.cited_by}
      />
    </div>
  );
}

function CitingTheses({ referenceId, onOpenThesis }) {
  const state = useAsync(() => api.bibliographyReference(referenceId), [referenceId]);
  return (
    <AsyncBoundary state={state}>
      {(data) => (
        <div className="card">
          <p className="chart-note">
            Cited by {count(data.cited_by)} thesis/theses. Each row shows that thesis&apos;s own
            wording — two visibly different strings under one work is exactly what the match tier
            is claiming, shown so it can be checked rather than trusted.
          </p>
          <DataTable
            columns={[
              {
                key: 'title',
                label: 'Thesis',
                render: (r) => (
                  <button type="button" className="link-button" onClick={() => onOpenThesis(r.handle)}>
                    {r.title}
                  </button>
                ),
              },
              { key: 'year', label: 'Year', numeric: true },
              { key: 'entry_raw', label: 'As cited there', render: (r) => <span className="chart-note">{r.entry_raw}</span> },
            ]}
            rows={data.theses}
            getKey={(r) => r.handle}
          />
        </div>
      )}
    </AsyncBoundary>
  );
}

function ReferenceTable({ minCitedBy, q, tier, onOpenThesis }) {
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState(null);
  useEffect(() => {
    setOffset(0);
    setExpanded(null);
  }, [minCitedBy, q, tier]);

  const state = useAsync(
    () => api.bibliography({ minCitedBy, q: q || undefined, tier: tier || undefined, limit: PAGE_SIZE, offset }),
    [minCitedBy, q, tier, offset],
  );

  return (
    <AsyncBoundary state={state}>
      {(data) => (
        <div className="card">
          <p className="chart-note">
            {count(data.total)} distinct work(s) cited by at least {data.min_cited_by} thesis/theses
            {data.q ? ` matching “${data.q}”` : ''}
            {data.tier ? ` at tier ${TIER_LABEL[data.tier]}` : ''}
          </p>
          <DataTable
            columns={[
              {
                key: 'display_string',
                label: 'Reference',
                render: (r) => (
                  <button
                    type="button"
                    className="link-button"
                    aria-expanded={expanded === r.id}
                    onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                  >
                    {r.display_string}
                  </button>
                ),
              },
              { key: 'year', label: 'Year', numeric: true, render: (r) => r.year || '—' },
              { key: 'cited_by', label: 'Citing theses', numeric: true, render: (r) => count(r.cited_by) },
              { key: 'match_tier', label: 'Matched by', render: (r) => <TierBadge tier={r.match_tier} /> },
              {
                key: 'doi',
                label: 'DOI',
                render: (r) =>
                  r.doi ? (
                    <a href={`https://doi.org/${r.doi}`} target="_blank" rel="noreferrer noopener">
                      {r.doi}
                    </a>
                  ) : (
                    <span className="chart-note">—</span>
                  ),
              },
            ]}
            rows={data.references}
            getKey={(r) => r.id}
          />
          {expanded != null ? <CitingTheses referenceId={expanded} onOpenThesis={onOpenThesis} /> : null}
          <div className="pager">
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              ← Previous
            </button>
            <span className="pager-status">
              {data.total === 0
                ? 'No results'
                : `${offset + 1}–${Math.min(offset + PAGE_SIZE, data.total)} of ${count(data.total)}`}
            </span>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= data.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next →
            </button>
          </div>
          <Caveat>{data.caveat}</Caveat>
          <Caveat label="match_tier">{data.match_tier_caveat}</Caveat>
        </div>
      )}
    </AsyncBoundary>
  );
}

function Coverage() {
  const state = useAsync(() => api.bibliographyTheses(), []);
  return (
    <AsyncBoundary state={state}>
      {(data) => {
        const empty = data.theses.filter((t) => t.reference_count === 0);
        const stubs = empty.filter((t) => !t.full_text).length;
        return (
          <div className="card">
            <p className="chart-note">
              {count(data.theses.length - empty.length)} of {count(data.theses.length)} theses
              contributed references. Of the {count(empty.length)} that did not, {count(stubs)} are
              metadata-only stubs with no body text at all and {count(empty.length - stubs)} have a
              body whose bibliography the parser could not find — a real miss, listed by name so it
              is countable rather than implied.
            </p>
            <DataTable
              columns={[
                { key: 'title', label: 'Thesis' },
                { key: 'year', label: 'Year', numeric: true },
                {
                  key: 'full_text',
                  label: 'Body text?',
                  render: (r) => (r.full_text ? 'yes' : <span className="chart-note">no (stub)</span>),
                },
                { key: 'reference_count', label: 'References parsed', numeric: true, render: (r) => count(r.reference_count) },
              ]}
              rows={data.theses}
              getKey={(r) => r.handle}
            />
            <Caveat>{data.caveat}</Caveat>
          </div>
        );
      }}
    </AsyncBoundary>
  );
}

export default function Bibliography({ onOpenThesis }) {
  const summaryState = useAsync(() => api.bibliographySummary(), []);
  const [minCitedBy, setMinCitedBy] = useState(null);
  const [tier, setTier] = useState(null);
  const [input, setInput] = useState('');
  const [q, setQ] = useState('');
  const [showCoverage, setShowCoverage] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setQ(input.trim()), 250);
    return () => clearTimeout(t);
  }, [input]);

  return (
    <Section
      title="Bibliography"
      note="Every work cited anywhere in the thesis corpus, ranked by how many theses cite it. Parsed offline out of the extracted PDF text — not collected, and not complete: read the two caveats under the table before quoting a number from it."
    >
      <AsyncBoundary state={summaryState}>
        {(summary) => {
          // The floor is seeded from the server's own constant rather than
          // duplicated here, so changing DEFAULT_MIN_CITED_BY moves both.
          const floor = minCitedBy ?? summary.default_min_cited_by;
          return (
            <>
              <div className="tiles">
                <Tile value={count(summary.references_total)} label="Distinct works" />
                <Tile
                  value={count(summary.shared_references)}
                  label="Cited by 2+ theses"
                  note={`${((summary.shared_references / summary.references_total) * 100).toFixed(1)}% of the corpus`}
                />
                <Tile value={count(summary.citations_total)} label="Citations" />
                <Tile
                  value={`${count(summary.theses_with_references)} / ${count(summary.theses_total)}`}
                  label="Theses parsed"
                  note={`${count(summary.theses_with_body)} have body text at all`}
                />
              </div>

              <Distribution histogram={summary.cited_by_histogram} />

              <div className="group-pills">
                <span className="chart-note">Minimum citing theses:</span>
                {FLOOR_OPTIONS.map((n) => (
                  <button
                    key={n}
                    type="button"
                    className="group-pill"
                    aria-pressed={floor === n}
                    onClick={() => setMinCitedBy(n)}
                  >
                    ≥{n}
                  </button>
                ))}
                <span className="chart-note">
                  ≥1 is the full {count(summary.references_total)}-work list — 97% of it is works
                  cited exactly once, which is a real property of this corpus, not a gap.
                </span>
              </div>

              <div className="group-pills">
                <span className="chart-note">Matched by:</span>
                <button type="button" className="group-pill" aria-pressed={tier === null} onClick={() => setTier(null)}>
                  Any
                </button>
                {summary.match_tiers.map((t) => (
                  <button
                    key={t.match_tier}
                    type="button"
                    className="group-pill"
                    aria-pressed={tier === t.match_tier}
                    onClick={() => setTier(t.match_tier)}
                    title={`${count(t.reference_count)} works`}
                  >
                    {TIER_LABEL[t.match_tier]} ({count(t.reference_count)})
                  </button>
                ))}
              </div>

              <div className="filters">
                <input
                  type="search"
                  value={input}
                  placeholder="Search the reference text or a DOI…"
                  aria-label="Search references"
                  onChange={(e) => setInput(e.target.value)}
                />
                <button type="button" className="link-button" onClick={() => setShowCoverage(!showCoverage)}>
                  {showCoverage ? 'Hide coverage' : 'Which theses contributed?'}
                </button>
              </div>

              {showCoverage ? <Coverage /> : null}

              <ReferenceTable minCitedBy={floor} q={q} tier={tier} onOpenThesis={onOpenThesis} />
            </>
          );
        }}
      </AsyncBoundary>
    </Section>
  );
}
