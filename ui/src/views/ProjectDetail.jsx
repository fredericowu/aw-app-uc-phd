// One project, in full — the second thing the static presentation could never
// do.
//
// The `fields_raw` table at the bottom is the point of this view. It is every
// (label, value) pair the site published for this project, verbatim and in
// document order, including labels the scraper never promoted to a typed
// column (Keywords being the known case). Anything the typed sections above
// miss is still visible there, so this view cannot silently drop a field the
// site started publishing after the parser was written.

import { api } from '../api';
import { AsyncBoundary, DataTable, ExternalLink, useAsync } from '../components';
import { groupColorVar } from '../colors';
import { date, money } from '../format';

function Field({ label, children }) {
  if (children == null || children === '' || children === '—') return null;
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

export default function ProjectDetail({ projectId, onBack }) {
  const state = useAsync(() => api.project(projectId), [projectId]);
  return (
    <section className="section">
      <button type="button" className="table-toggle" onClick={onBack}>
        ← Back
      </button>
      <AsyncBoundary state={state}>
        {({ project: p }) => (
          <>
            <div className="detail-header">
              <h2>{p.title}</h2>
              <div className="detail-meta">
                {p.groups.map((g) => (
                  <span className="legend-item" key={g.code}>
                    <span className="swatch" style={{ background: groupColorVar(g.code) }} />
                    {g.code} — {g.name}
                  </span>
                ))}
                {p.detail_url ? (
                  <ExternalLink href={p.detail_url}>Open on cisuc.uc.pt</ExternalLink>
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}>
                    {p.detail_unavailable_reason || 'No detail page published by the site'}
                  </span>
                )}
              </div>
            </div>

            {p.synopsis ? (
              <div className="card section">
                <p className="chart-title">Synopsis</p>
                <p className="detail-synopsis">{p.synopsis}</p>
              </div>
            ) : null}

            <div className="grid section">
              <div className="card">
                <p className="chart-title">Facts</p>
                <dl className="kv">
                  <Field label="Scope">{p.scope}</Field>
                  <Field label="Funding">{p.funding_raw}</Field>
                  <Field label="Start date">{date(p.start_date) !== '—' ? date(p.start_date) : p.start_date_raw}</Field>
                  <Field label="End date">{date(p.end_date) !== '—' ? date(p.end_date) : p.end_date_raw}</Field>
                  <Field label="Total budget">
                    {p.total_budget_amount != null ? money(p.total_budget_amount) : p.total_budget_raw}
                  </Field>
                  <Field label="CISUC budget">
                    {p.cisuc_budget_amount != null ? money(p.cisuc_budget_amount) : p.cisuc_budget_raw}
                  </Field>
                  <Field label="Partners">{p.partners_raw}</Field>
                  <Field label="Last scraped">{p.last_scraped_at}</Field>
                </dl>
              </div>

              <div className="card">
                <p className="chart-title">People</p>
                {p.people.length ? (
                  <DataTable
                    columns={[
                      { key: 'name', label: 'Name' },
                      { key: 'role', label: 'Role' },
                    ]}
                    rows={p.people}
                    getKey={(r) => `${r.slug}-${r.role}`}
                  />
                ) : (
                  <p className="chart-note">No people listed.</p>
                )}
              </div>
            </div>

            {p.keywords.length ? (
              <div className="card section">
                <p className="chart-title">Keywords</p>
                <div className="chips">
                  {p.keywords.map((k) => (
                    <span className="chip" key={k}>
                      {k}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="card">
              <p className="chart-title">Every field the site publishes</p>
              <p className="chart-note">
                Raw (label, value) pairs from the project's page, in document order — including
                any label that has no typed column above.
              </p>
              {p.fields_raw.length ? (
                <DataTable
                  columns={[
                    { key: 'label', label: 'Label' },
                    {
                      key: 'value_text',
                      label: 'Value',
                      render: (r) =>
                        r.href ? (
                          <a href={r.href} target="_blank" rel="noreferrer noopener">
                            {r.value_text || r.href}
                          </a>
                        ) : (
                          r.value_text || '—'
                        ),
                    },
                  ]}
                  rows={p.fields_raw}
                  getKey={(r, i) => `${r.label}-${r.ordinal}-${i}`}
                />
              ) : (
                <p className="chart-note">
                  No detail page was fetched for this project, so there are no raw fields.
                </p>
              )}
            </div>
          </>
        )}
      </AsyncBoundary>
    </section>
  );
}
