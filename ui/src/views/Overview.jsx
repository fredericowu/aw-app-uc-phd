// Coverage and field completeness — the two "can you trust this data?"
// sections, kept first because every other number depends on the answer.

import { api } from '../api';
import {
  AsyncBoundary,
  Caveat,
  CategoryBars,
  ChartWithTable,
  Section,
  Tile,
  useAsync,
} from '../components';
import { SEQUENTIAL } from '../colors';
import { count, percent } from '../format';

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

function FillRates() {
  const state = useAsync(() => api.fillRates(), []);
  return (
    <AsyncBoundary state={state}>
      {({ fields }) => (
        <ChartWithTable
          title="Field completeness"
          note="Share of fetched detail pages carrying each field"
          columns={[
            { key: 'label', label: 'Field' },
            {
              key: 'projects_with_field',
              label: 'Projects',
              numeric: true,
              render: (r) => count(r.projects_with_field),
            },
            {
              key: 'fill_rate_pct',
              label: 'Fill rate',
              numeric: true,
              render: (r) => percent(r.fill_rate_pct),
            },
          ]}
          rows={fields}
          getKey={(r) => r.label}
        >
          <CategoryBars
            data={fields}
            categoryKey="label"
            valueKey="fill_rate_pct"
            slotOf={() => SEQUENTIAL}
            valueFormat={percent}
            seriesLabel="Fill rate"
            categoryWidth={130}
          />
        </ChartWithTable>
      )}
    </AsyncBoundary>
  );
}

export default function Overview() {
  return (
    <>
      <Section
        title="Coverage"
        note="What the scraper actually got, measured against the site's own count rather than asserted."
      >
        <Coverage />
      </Section>
      <Section
        title="Field completeness"
        note="Driven by the site's own label universe, not a hardcoded field list — a field nobody thought to name still appears here. Source: sql/fill_rates.sql."
      >
        <FillRates />
      </Section>
    </>
  );
}
