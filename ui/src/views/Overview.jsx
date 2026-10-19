// At a glance, then Coverage — the "can you trust this data?" section, kept
// second because every other number depends on the answer.

import { useState } from 'react';
import { api } from '../api';
import { AsyncBoundary, Caveat, DataTable, ExternalLink, Section, Tile, useAsync } from '../components';
import { GROUP_ORDER } from '../colors';
import { count } from '../format';

/** A student's identity for dedup, mirroring the backend's own tiebreak
 *  (see uc_phd_app/theses.py): a resolved author dedupes on the person's
 *  slug, so the same student across two theses counts once; an
 *  unattributed name has no slug to key on, so it counts on its own name
 *  instead — the same tradeoff every other unattributed-name figure in
 *  this app makes. */
function studentKey(author) {
  return author.matched.length ? `slug:${author.matched[0].slug}` : `name:${author.name}`;
}

/** Every student whose studentKey() appears on more than one thesis — the
 *  list the "Students" tile's "+N more" toggle expands into. Grouped from
 *  the same `theses` payload AtAGlance already fetched, so expanding this
 *  costs no extra request. */
function repeatStudentGroups(theses) {
  const byKey = new Map();
  for (const thesis of theses) {
    for (const author of thesis.authors) {
      const key = studentKey(author);
      if (!byKey.has(key)) byKey.set(key, { key, author, theses: [] });
      byKey.get(key).theses.push(thesis);
    }
  }
  return [...byKey.values()].filter((g) => g.theses.length > 1);
}

/** Where to verify a repeat student's identity against the source that
 *  actually names them: CISUC's own people page for a matched CISUC person
 *  — `people.slug` is sourced straight from that URL (scraper/people.py,
 *  tests/test_detail_parser.py), so this is a stable, already-used
 *  convention, not a new one — or a UC-unit-directory page when `directory`
 *  is present instead (`directory.person_url`, falling back to
 *  `directory.listing_url`, same preference PersonDetail.jsx already uses).
 *
 *  A name the matcher correctly left unattributed — e.g. "Soma, Paulo"
 *  (docs/design/uc-phd-soma-paulo-identity.md: an Angola-based jurist, not
 *  UC staff) — has no identity page to link, by design. That absence must
 *  read as "not UC staff", never as a dropped link, so this renders an
 *  explicit note instead of silently omitting the link. */
function RepeatStudentLink({ author }) {
  if (author.matched.length) {
    const directory = author.directory;
    const href = directory
      ? directory.person_url || directory.listing_url
      : `https://www.cisuc.uc.pt/en/people/${encodeURIComponent(author.matched[0].slug)}`;
    return <ExternalLink href={href}>{author.name}</ExternalLink>;
  }
  return (
    <>
      <span>{author.name}</span>
      <div className="tile-note">
        Not UC staff — no UC people page exists. Verify via the theses' own Estudo Geral pages →
      </div>
    </>
  );
}

/** The repeat-student list itself, lazy-rendered only once expanded — each
 *  row pairs the student (see RepeatStudentLink above) with every one of
 *  their own theses, each linked to its Estudo Geral source page so the
 *  claim "these are the same person" can be checked thesis by thesis. */
function RepeatStudents({ groups }) {
  return (
    <DataTable
      columns={[
        { key: 'student', label: 'Student', render: (g) => <RepeatStudentLink author={g.author} /> },
        {
          key: 'theses',
          label: 'Theses',
          render: (g) => (
            <ul className="repeat-student-theses">
              {g.theses.map((t) => (
                <li key={t.handle}>
                  <ExternalLink href={t.source_url}>{t.title}</ExternalLink>
                </li>
              ))}
            </ul>
          ),
        },
      ]}
      rows={groups}
      getKey={(g) => g.key}
    />
  );
}

function AtAGlance() {
  const coverageState = useAsync(() => api.coverage(), []);
  const thesesState = useAsync(() => api.theses(), []);
  const coordinatorsState = useAsync(() => api.coordinators(), []);
  const [expanded, setExpanded] = useState(false);

  if (coverageState.loading || thesesState.loading || coordinatorsState.loading) {
    return <p className="state">Loading…</p>;
  }
  const error = coverageState.error || thesesState.error || coordinatorsState.error;
  if (error) return <p className="state error">{error.message}</p>;
  if (!coverageState.data || !thesesState.data || !coordinatorsState.data) return null;

  const theses = thesesState.data.theses;
  const thesisCount = theses.length;
  const studentCount = new Set(theses.flatMap((t) => t.authors.map(studentKey))).size;
  const projectCount = coverageState.data.coverage.total_projects;
  const coordinatorCount = coordinatorsState.data.coordinators.length;
  const repeatStudents = thesisCount - studentCount;
  const repeats = repeatStudentGroups(theses);

  return (
    <>
      <div className="tiles">
        <Tile value={count(thesisCount)} label="Theses" />
        <div className="tile">
          <div className="tile-value">{count(studentCount)}</div>
          <div className="tile-label">Students</div>
          {repeatStudents > 0 ? (
            <div className="tile-note">
              {count(repeatStudents)} student{repeatStudents === 1 ? '' : 's'}{' '}
              {repeatStudents === 1 ? 'appears' : 'appear'} as author on more than one thesis
            </div>
          ) : null}
          {repeats.length > 0 ? (
            <button
              type="button"
              className="table-toggle"
              aria-expanded={expanded}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? 'Show fewer' : `+ ${count(repeats.length)} more`}
            </button>
          ) : null}
        </div>
        <Tile value={count(projectCount)} label="Projects" />
        <Tile value={count(coordinatorCount)} label="Coordinators" note="By the coordinator role on a project — see Coordinators" />
        <Tile value={count(GROUP_ORDER.length)} label="Research groups" />
      </div>
      {expanded ? <RepeatStudents groups={repeats} /> : null}
    </>
  );
}

/** Lazy-fetched only once the "No detail page" tile is expanded — the list
 *  the tile's count is summarizing, each title wired straight into the same
 *  in-app project detail view the Projects tab opens (never the external
 *  site: these are exactly the projects for which it has none). */
function NoDetailProjects({ onOpenProject }) {
  const state = useAsync(() => api.projects({ detailUnavailable: true, limit: 500 }), []);
  return (
    <AsyncBoundary state={state}>
      {(data) => (
        <DataTable
          columns={[
            {
              key: 'title',
              label: 'Project',
              render: (r) => (
                <button type="button" className="link-button" onClick={() => onOpenProject(r.id)}>
                  {r.title}
                </button>
              ),
            },
          ]}
          rows={data.projects}
          getKey={(r) => r.id}
        />
      )}
    </AsyncBoundary>
  );
}

function Coverage({ onOpenProject }) {
  const state = useAsync(() => api.coverage(), []);
  const [expanded, setExpanded] = useState(false);
  return (
    <AsyncBoundary state={state}>
      {({ coverage: c }) => (
        <>
          <div className="tiles">
            <Tile
              value={count(c.total_projects)}
              label="Projects in the database"
              note={
                c.site_total_data != null
                  ? `The site's own total at scrape time: ${count(c.site_total_data)}`
                  : undefined
              }
            />
            <Tile value={count(c.detail_fetched_ok)} label="Detail pages fetched" />
            <div className="tile">
              <div className="tile-value">{count(c.detail_unavailable)}</div>
              <div className="tile-label">No detail page</div>
              <div className="tile-note">The site publishes none for these</div>
              {c.detail_unavailable > 0 ? (
                <button
                  type="button"
                  className="table-toggle"
                  aria-expanded={expanded}
                  onClick={() => setExpanded((v) => !v)}
                >
                  {expanded ? 'Show fewer' : `+ ${count(c.detail_unavailable)} more`}
                </button>
              ) : null}
            </div>
            <Tile value={count(c.null_titles)} label="Projects with no title" />
            <Tile
              value={`${count(c.scrape_targets_terminal)} / ${count(c.scrape_targets_rows)}`}
              label="Scrape targets resolved"
              note="Every listing row reached a terminal status"
            />
          </div>
          {expanded ? <NoDetailProjects onOpenProject={onOpenProject} /> : null}
          <Caveat label="Why three different totals">
            Each number counts something different and all three are correct.
            The database holds every project the listing published; a smaller
            number have a detail page the site actually serves; the scrape
            manifest tracks whether each listing row was resolved rather than
            merely counted. Source: <code>sql/coverage.sql</code>.
          </Caveat>
        </>
      )}
    </AsyncBoundary>
  );
}

export default function Overview({ onOpenProject }) {
  return (
    <>
      <Section
        title="At a glance"
        note="Real counts across the corpus — each one comes from the same committed queries as the rest of the app, not a hand-typed estimate."
      >
        <AtAGlance />
        <Caveat label="Data sources">
          Theses come from Estudo Geral, UC's institutional repository — the
          DEI{' '}
          <a href="https://estudogeral.uc.pt/handle/10316/103" target="_blank" rel="noreferrer noopener">
            "Teses de Doutoramento" collection
          </a>
          . Projects come from CISUC's own{' '}
          <a href="https://www.cisuc.uc.pt/en/projects" target="_blank" rel="noreferrer noopener">
            projects listing
          </a>
          .
        </Caveat>
      </Section>
      <Section
        title="Coverage"
        note="What the scraper actually got, measured against the site's own count rather than asserted."
      >
        <Coverage onOpenProject={onOpenProject} />
      </Section>
    </>
  );
}
