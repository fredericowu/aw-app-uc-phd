// At a glance, then Coverage — the "can you trust this data?" section, kept
// second because every other number depends on the answer.

import { api } from '../api';
import { AsyncBoundary, Caveat, Section, Tile, useAsync } from '../components';
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

function AtAGlance() {
  const coverageState = useAsync(() => api.coverage(), []);
  const thesesState = useAsync(() => api.theses(), []);
  const coordinatorsState = useAsync(() => api.coordinators(), []);

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

  return (
    <div className="tiles">
      <Tile value={count(thesisCount)} label="Theses" />
      <Tile
        value={count(studentCount)}
        label="Students"
        note={
          repeatStudents > 0
            ? `${count(repeatStudents)} student${repeatStudents === 1 ? '' : 's'} ` +
              `${repeatStudents === 1 ? 'appears' : 'appear'} as author on more than one thesis`
            : 'One thesis, one student, so far'
        }
      />
      <Tile value={count(projectCount)} label="Projects" />
      <Tile value={count(coordinatorCount)} label="Coordinators" note="By the coordinator role on a project — see Coordinators" />
      <Tile value={count(GROUP_ORDER.length)} label="Research groups" />
    </div>
  );
}

function Coverage() {
  const state = useAsync(() => api.coverage(), []);
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
            <Tile
              value={count(c.detail_unavailable)}
              label="No detail page"
              note="The site publishes none for these"
            />
            <Tile value={count(c.null_titles)} label="Projects with no title" />
            <Tile
              value={`${count(c.scrape_targets_terminal)} / ${count(c.scrape_targets_rows)}`}
              label="Scrape targets resolved"
              note="Every listing row reached a terminal status"
            />
          </div>
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

export default function Overview() {
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
        <Coverage />
      </Section>
    </>
  );
}
