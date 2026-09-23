// Coverage — the "can you trust this data?" section, kept first because
// every other number depends on the answer.

import { api } from '../api';
import { AsyncBoundary, Caveat, Section, Tile, useAsync } from '../components';
import { count } from '../format';

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
    <Section
      title="Coverage"
      note="What the scraper actually got, measured against the site's own count rather than asserted."
    >
      <Coverage />
    </Section>
  );
}
