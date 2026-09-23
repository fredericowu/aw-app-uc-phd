// Research groups: how many projects each runs, and how much budget sits under
// each. Both figures are many-to-many, and the caveat says so on both.

import { api } from '../api';
import {
  AsyncBoundary,
  Caveat,
  CategoryBars,
  ChartWithTable,
  GroupLegend,
  Section,
  useAsync,
} from '../components';
import { groupColorVar, groupSlot } from '../colors';
import { count, money, moneyCompact } from '../format';

export default function Groups() {
  const counts = useAsync(() => api.groups(), []);
  const budgets = useAsync(() => api.budgetByGroup(), []);

  return (
    <Section
      title="Research groups"
      note="All six CISUC groups. Colour identifies a group and stays with it on every chart in this app."
    >
      <AsyncBoundary state={counts}>
        {(data) => (
          <>
            <Caveat label="Many-to-many">{data.caveat}</Caveat>
            <div className="grid">
              <ChartWithTable
                title="Projects per group"
                note="Source: sql/projects_per_group.sql"
                columns={[
                  { key: 'code', label: 'Group' },
                  { key: 'name', label: 'Name' },
                  {
                    key: 'project_count',
                    label: 'Projects',
                    numeric: true,
                    render: (r) => count(r.project_count),
                  },
                ]}
                rows={data.groups}
                getKey={(r) => r.code}
              >
                <CategoryBars
                  data={data.groups}
                  categoryKey="code"
                  valueKey="project_count"
                  slotOf={(d) => groupSlot(d.code)}
                  valueFormat={count}
                  seriesLabel="Projects"
                  categoryWidth={50}
                  height={200}
                />
              </ChartWithTable>

              <AsyncBoundary state={budgets}>
                {(b) => (
                  <ChartWithTable
                    title="Total budget per group"
                    note="Only projects with a parsed budget amount. Source: sql/budget_by_group.sql"
                    columns={[
                      { key: 'code', label: 'Group' },
                      { key: 'name', label: 'Name' },
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
                    rows={b.groups}
                    getKey={(r) => r.code}
                  >
                    <CategoryBars
                      data={b.groups}
                      categoryKey="code"
                      valueKey="total_budget_sum"
                      slotOf={(d) => groupSlot(d.code)}
                      valueFormat={moneyCompact}
                      seriesLabel="Total budget"
                      categoryWidth={50}
                      height={200}
                    />
                  </ChartWithTable>
                )}
              </AsyncBoundary>
            </div>
            <GroupLegend groups={data.groups} colorOf={(g) => groupColorVar(g.code)} />
          </>
        )}
      </AsyncBoundary>
    </Section>
  );
}
