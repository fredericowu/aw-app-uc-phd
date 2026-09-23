// Funding, budget by year, and the start-date timeline.
//
// Budget-per-year and projects-per-year are two measures on different scales
// over the same x. They get two charts, never one with two y-axes.

import { api } from '../api';
import {
  AsyncBoundary,
  CategoryBars,
  ChartWithTable,
  Section,
  TimeLine,
  useAsync,
} from '../components';
import { SEQUENTIAL } from '../colors';
import { count, money, moneyCompact, truncate } from '../format';

function Funding() {
  const state = useAsync(() => api.funding(), []);
  return (
    <AsyncBoundary state={state}>
      {({ funders }) => (
        <ChartWithTable
          title="Projects per funding source"
          note="Top 15 funders by project count; the long tail is collapsed into “Other”. The site publishes a funder name, not a funding category — none is invented here. Source: sql/funding_breakdown.sql"
          columns={[
            { key: 'funder', label: 'Funder' },
            {
              key: 'project_count',
              label: 'Projects',
              numeric: true,
              render: (r) => count(r.project_count),
            },
          ]}
          rows={funders}
          getKey={(r) => r.funder}
        >
          <CategoryBars
            data={funders.map((f) => ({ ...f, funder_short: truncate(f.funder, 34) }))}
            categoryKey="funder_short"
            valueKey="project_count"
            slotOf={() => SEQUENTIAL}
            valueFormat={count}
            seriesLabel="Projects"
            categoryWidth={220}
          />
        </ChartWithTable>
      )}
    </AsyncBoundary>
  );
}

function BudgetByYear() {
  const state = useAsync(() => api.budgetByYear(), []);
  return (
    <AsyncBoundary state={state}>
      {({ years }) => (
        <ChartWithTable
          title="Total budget by start year"
          note="Only projects with a parseable start date contribute — an unreadable date is excluded rather than guessed at. Source: sql/budget_by_year.sql"
          columns={[
            { key: 'start_year', label: 'Year' },
            {
              key: 'project_count',
              label: 'Projects',
              numeric: true,
              render: (r) => count(r.project_count),
            },
            {
              key: 'total_budget_sum',
              label: 'Total budget',
              numeric: true,
              render: (r) => money(r.total_budget_sum),
            },
          ]}
          rows={years}
          getKey={(r) => r.start_year}
        >
          <TimeLine
            data={years}
            categoryKey="start_year"
            valueKey="total_budget_sum"
            valueFormat={moneyCompact}
            seriesLabel="Total budget"
          />
        </ChartWithTable>
      )}
    </AsyncBoundary>
  );
}

function Timeline() {
  const state = useAsync(() => api.timeline(), []);
  return (
    <AsyncBoundary state={state}>
      {({ years }) => (
        <ChartWithTable
          title="Projects started per year"
          note="Source: sql/start_date_timeline.sql"
          columns={[
            { key: 'start_year', label: 'Year' },
            {
              key: 'project_count',
              label: 'Projects',
              numeric: true,
              render: (r) => count(r.project_count),
            },
          ]}
          rows={years}
          getKey={(r) => r.start_year}
        >
          <TimeLine
            data={years}
            categoryKey="start_year"
            valueKey="project_count"
            valueFormat={count}
            seriesLabel="Projects started"
          />
        </ChartWithTable>
      )}
    </AsyncBoundary>
  );
}

export default function Money() {
  return (
    <>
      <Section title="Funding" note="Where the projects' money comes from.">
        <Funding />
      </Section>
      <Section
        title="Budget and timeline"
        note="Two measures on the same years, kept on two charts — a single chart with two y-axes would invite a comparison the scales do not support."
      >
        <div className="grid">
          <BudgetByYear />
          <Timeline />
        </div>
      </Section>
    </>
  );
}
