// One researcher/collaborator — same shape as ProjectDetail.jsx and
// ThesisDetail.jsx (back button + header + AsyncBoundary), adapted for a
// person.
//
// READ THE CAVEAT AT THE TOP OF THE PAGE BEFORE ADDING ANYTHING HERE. The
// `people` table is `(slug, name)` and nothing else — no photo, no bio, no
// email, no publication count. This page can only ever show what someone is
// CONNECTED to, never who they are, and it says so on screen rather than
// leaving a reader to infer it from the absence of a face.
//
// The collaborator section is fetched from a SEPARATE endpoint
// (/collab/people/{slug}) for the same reason ThesisDetail fetches its body
// separately: collab.enriched_pairs() recomputes all 4,242 pairs in Python on
// every call, and the header must not block on that.

import { api } from '../api';
import {
  AsyncBoundary,
  Caveat,
  DataTable,
  ExternalLink,
  PersonLink,
  Tile,
  useAsync,
} from '../components';
import { groupColorVar } from '../colors';
import { count, date, money } from '../format';

const ROLE_LABEL = { coordinator: 'Coordinator', researcher: 'Researcher' };

function GroupChips({ groups }) {
  if (!groups.length) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
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

function Roles({ roles }) {
  return roles.map((r) => ROLE_LABEL[r] || r).join(' + ');
}

/** Keyword frequencies, kept separate by source and labelled — project
 *  keywords come from CISUC, thesis keywords from Estudo Geral. Two
 *  vocabularies, never merged into one cloud that would imply they are
 *  comparable. */
function KeywordChips({ items, countKey, unit }) {
  if (!items.length) return <p className="chart-note">None recorded.</p>;
  return (
    <div className="chips">
      {items.map((k) => (
        <span className="chip" key={k.keyword} title={`${count(k[countKey])} ${unit}`}>
          {k.keyword}
          {k[countKey] > 1 ? ` ·${k[countKey]}` : ''}
        </span>
      ))}
    </div>
  );
}

function ThesisList({ items, emptyNote }) {
  if (!items.length) return <p className="chart-note">{emptyNote}</p>;
  return (
    <DataTable
      columns={[
        {
          key: 'title',
          label: 'Thesis',
          render: (t) => (
            // Deep-links into the existing thesis detail route. Handles carry
            // a slash, so each segment is encoded on its own and rejoined
            // with a literal "/" — the same contract App.jsx's openThesis()
            // and api.js's thesis() both use.
            <a href={`#/theses/${t.handle.split('/').map(encodeURIComponent).join('/')}`}>
              {t.title}
            </a>
          ),
        },
        { key: 'year', label: 'Year', render: (t) => t.year || '—' },
        {
          key: 'full_text',
          label: 'Full text',
          render: (t) => (t.full_text ? 'indexed' : 'not indexed'),
        },
      ]}
      rows={items}
      getKey={(t) => t.handle}
    />
  );
}

/** The collaborator neighbourhood, from the pre-existing /collab endpoint.
 *  Its own AsyncBoundary, so a slow or failed pairs computation degrades this
 *  one card instead of the whole profile. */
function Collaborators({ slug }) {
  const state = useAsync(() => api.collabPerson(slug, { kind: 'co_project', minWeight: 1 }), [slug]);
  return (
    <div className="card section">
      <p className="chart-title">Collaborators</p>
      <p className="chart-note">
        People listed on at least one of the same projects. Co-supervision is a different
        relationship and is not summed into this — see Collaboration &amp; teams for that view.
      </p>
      <AsyncBoundary state={state}>
        {(data) =>
          data.collaborators.length ? (
            <>
              <DataTable
                columns={[
                  {
                    key: 'name',
                    label: 'Collaborator',
                    render: (c) => <PersonLink slug={c.slug}>{c.name}</PersonLink>,
                  },
                  { key: 'groups', label: 'Groups', render: (c) => <GroupChips groups={c.groups} /> },
                  {
                    key: 'weight',
                    label: 'Shared projects',
                    numeric: true,
                    render: (c) => count(c.weight),
                  },
                ]}
                rows={data.collaborators}
                getKey={(c) => c.slug}
              />
              <Caveat>{data.caveat}</Caveat>
            </>
          ) : (
            <p className="chart-note">
              No co-listed collaborator — every project this person appears on lists nobody else.
            </p>
          )
        }
      </AsyncBoundary>
    </div>
  );
}

export default function PersonDetail({ slug, onBack }) {
  const state = useAsync(() => api.person(slug), [slug]);

  return (
    <section className="section">
      <button type="button" className="table-toggle" onClick={onBack}>
        ← Back
      </button>
      <AsyncBoundary state={state}>
        {(data) => {
          const { person, projects, theses, keywords } = data;
          return (
            <>
              <div className="detail-header">
                <h2>{person.name}</h2>
                <div className="detail-meta">
                  <GroupChips groups={person.groups} />
                  {/* Never a reconstructed URL: this is the href the site
                      itself published, read from project_fields_raw. No
                      stored href means no link at all. */}
                  {person.cisuc_url ? (
                    <ExternalLink href={person.cisuc_url}>Open on cisuc.uc.pt</ExternalLink>
                  ) : (
                    <span style={{ color: 'var(--text-muted)' }}>
                      No CISUC profile URL published for this person
                    </span>
                  )}
                </div>
              </div>

              <Caveat label="What this page is">{data.caveat}</Caveat>

              {person.name_siblings.length ? (
                <Caveat label="Same name, different profile">
                  {data.duplicate_name_caveat}{' '}
                  {person.name_siblings.map((s, i) => (
                    <span key={s.slug}>
                      {i > 0 ? ', ' : ''}
                      <PersonLink slug={s.slug}>{s.slug}</PersonLink>
                    </span>
                  ))}
                </Caveat>
              ) : null}

              {/* Authored and supervised stay two tiles, never one "theses"
                  number — someone can author one and supervise nine, and a
                  sum describes neither. */}
              <div className="tiles">
                <Tile value={count(projects.project_count)} label="Projects" />
                <Tile value={count(projects.coordinated_count)} label="Coordinated" />
                <Tile value={count(theses.authored.length)} label="Theses authored" />
                <Tile value={count(theses.supervised.length)} label="Theses supervised" />
              </div>

              <div className="card section">
                <p className="chart-title">Projects</p>
                {projects.items.length ? (
                  <>
                    <DataTable
                      columns={[
                        {
                          key: 'title',
                          label: 'Project',
                          render: (p) => <a href={`#/projects/${p.id}`}>{p.title}</a>,
                        },
                        { key: 'roles', label: 'Role', render: (p) => <Roles roles={p.roles} /> },
                        { key: 'groups', label: 'Groups', render: (p) => <GroupChips groups={p.groups} /> },
                        { key: 'start_date', label: 'Start', render: (p) => date(p.start_date) },
                        { key: 'end_date', label: 'End', render: (p) => date(p.end_date) },
                        {
                          key: 'total_budget_amount',
                          label: 'Total budget',
                          numeric: true,
                          render: (p) =>
                            p.total_budget_amount != null ? money(p.total_budget_amount) : '—',
                        },
                      ]}
                      rows={projects.items}
                      getKey={(p) => p.id}
                    />
                    <Caveat label="How these are counted">{projects.caveat}</Caveat>
                  </>
                ) : (
                  <p className="chart-note">No project lists this person.</p>
                )}
              </div>

              <div className="grid section">
                <div className="card">
                  <p className="chart-title">Theses authored</p>
                  <ThesisList
                    items={theses.authored}
                    emptyNote="No thesis in this corpus resolves to this person as its author."
                  />
                </div>
                <div className="card">
                  <p className="chart-title">Theses supervised</p>
                  <ThesisList
                    items={theses.supervised}
                    emptyNote="No thesis in this corpus resolves to this person as a supervisor."
                  />
                </div>
              </div>
              <Caveat label="How theses are attributed">{theses.caveat}</Caveat>

              <div className="grid section">
                <div className="card">
                  <p className="chart-title">Project keywords</p>
                  <KeywordChips items={keywords.project} countKey="project_count" unit="project(s)" />
                </div>
                <div className="card">
                  <p className="chart-title">Thesis keywords</p>
                  <KeywordChips items={keywords.thesis} countKey="thesis_count" unit="thesis/theses" />
                </div>
              </div>
              <Caveat label="Two vocabularies">{keywords.caveat}</Caveat>

              <Collaborators slug={slug} />
            </>
          );
        }}
      </AsyncBoundary>
    </section>
  );
}
