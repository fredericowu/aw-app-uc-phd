// Who coordinates the most projects. One series, so no legend — the title
// names it — with every bar directly labelled.

import { api } from '../api';
import { AsyncBoundary, CategoryBars, ChartWithTable, Section, useAsync } from '../components';
import { SEQUENTIAL } from '../colors';
import { count } from '../format';

export default function Coordinators() {
  const state = useAsync(() => api.coordinators(), []);
  return (
    <Section
      title="Coordinators"
      note="Counted by the coordinator role on each project, so a researcher listed only as a team member does not appear here."
    >
      <AsyncBoundary state={state}>
        {({ coordinators }) => (
          <ChartWithTable
            title="Top coordinators by projects coordinated"
            note="Source: sql/top_coordinators.sql"
            columns={[
              { key: 'coordinator', label: 'Coordinator' },
              {
                key: 'project_count',
                label: 'Projects',
                numeric: true,
                render: (r) => count(r.project_count),
              },
            ]}
            rows={coordinators}
            getKey={(r) => r.coordinator}
          >
            <CategoryBars
              data={coordinators}
              categoryKey="coordinator"
              valueKey="project_count"
              slotOf={() => SEQUENTIAL}
              valueFormat={count}
              seriesLabel="Projects coordinated"
              categoryWidth={190}
            />
          </ChartWithTable>
        )}
      </AsyncBoundary>
    </Section>
  );
}
