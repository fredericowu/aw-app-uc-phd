// One thesis, in full — same shape as ProjectDetail.jsx, adapted for a
// document instead of a project: the header carries identity/attribution
// metadata plus the Estudo Geral link, the body carries the extracted text.
//
// The body is fetched from a SEPARATE endpoint (/theses/{handle}/body) on
// purpose — see api/theses.py's docstring — so the header above never blocks
// on up to ~1.2 MB of uncompressed text. That split means three states have
// to stay distinct rather than collapsing into one generic "no body" message
// (Frederico's acceptance criteria: never fake or silently truncate):
//
//   1. full_text: false  — embargoed/not indexed. Known from the metadata
//      response alone; the body endpoint is never even called.
//   2. full_text: true, body: null — the thesis WAS indexed but its .md is
//      missing on disk (data drift). Distinct from #1: this is unexpected.
//   3. the body fetch itself fails (network/5xx) — distinct from both: the
//      document might well exist, we just could not load it this time.

import { api } from '../api';
import { AsyncBoundary, Caveat, ExternalLink, ResolvedPersonName, useAsync } from '../components';
import { groupColorVar } from '../colors';

function PersonList({ people }) {
  if (!people.length) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  return (
    <>
      {people.map((p, i) => (
        <span key={p.name}>
          {i > 0 ? ', ' : ''}
          {/* The match tier (exact/confident/ambiguous/unmatched) rides as a
              tooltip on the name — the same attribution-tier treatment used
              in Theses.jsx, not re-derived here. The name becomes a profile
              link only when it resolves to exactly one person; see
              ResolvedPersonName for why matched[0] is never picked. */}
          <ResolvedPersonName person={p} title={p.note || p.match_status || undefined} />
          {p.status !== 'matched' ? (
            <span style={{ color: 'var(--text-muted)' }}> (unattributed)</span>
          ) : null}
        </span>
      ))}
    </>
  );
}

function GroupChips({ groups }) {
  if (!groups.length) {
    return <span style={{ color: 'var(--text-muted)' }}>Unattributed</span>;
  }
  return (
    <span className="chips">
      {groups.map((g) => (
        <span key={g} className="legend-item">
          <span className="swatch" style={{ background: groupColorVar(g) }} />
          {g}
        </span>
      ))}
    </span>
  );
}

export default function ThesisDetail({ handle, onBack }) {
  const thesisState = useAsync(() => api.thesis(handle), [handle]);
  const fullText = thesisState.data ? thesisState.data.full_text : null;
  // Only hits /body once the header has told us the thesis was indexed —
  // an embargoed thesis (fullText === false) has no body to fetch at all.
  const bodyState = useAsync(
    () => (fullText ? api.thesisBody(handle) : Promise.resolve(null)),
    [handle, fullText],
  );

  return (
    <section className="section">
      <button type="button" className="table-toggle" onClick={onBack}>
        ← Back
      </button>
      <AsyncBoundary state={thesisState}>
        {(t) => (
          <>
            <div className="detail-header">
              <h2>{t.title}</h2>
              <div className="detail-meta">
                <span>
                  Author(s): <PersonList people={t.authors} />
                </span>
                <span>
                  Supervisor(s): <PersonList people={t.supervisors} />
                </span>
                <span>{t.year || '—'}</span>
                <GroupChips groups={t.groups} />
                {t.source_url ? (
                  <ExternalLink href={t.source_url}>Open on Estudo Geral</ExternalLink>
                ) : null}
              </div>
            </div>

            {(t.abstract_en || t.abstract_pt) ? (
              <div className="card section">
                <p className="chart-title">Abstract</p>
                {t.abstract_en ? <p className="detail-synopsis">{t.abstract_en}</p> : null}
                {t.abstract_pt ? <p className="detail-synopsis">{t.abstract_pt}</p> : null}
              </div>
            ) : null}

            {t.full_text ? (
              <div className="card section">
                <p className="chart-title">Full document</p>
                {bodyState.loading ? (
                  <p className="state">Loading document…</p>
                ) : bodyState.error ? (
                  <p className="state error">
                    Could not load the document body: {bodyState.error.message}
                  </p>
                ) : bodyState.data && bodyState.data.body != null ? (
                  <p className="thesis-body">{bodyState.data.body}</p>
                ) : (
                  <p className="state">
                    This thesis was indexed as full text, but the extracted document could not
                    be found — the source file may be missing from this deployment.
                  </p>
                )}
              </div>
            ) : (
              <Caveat label="Metadata only">
                The full text of this thesis was not indexed
                {t.rights === 'embargoedAccess' ? ' (embargoed)' : ''} — only the metadata and
                abstract(s) above are available.
              </Caveat>
            )}
          </>
        )}
      </AsyncBoundary>
    </section>
  );
}
