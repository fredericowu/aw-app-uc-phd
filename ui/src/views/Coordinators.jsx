// Who coordinates the most projects, split by which research group(s) their
// projects belong to — colour carries group identity, same as every other
// per-group chart in this app.

import { api } from '../api';
import {
  AsyncBoundary,
  ChartWithTable,
  GroupLegend,
  Section,
  StackedCategoryBars,
  useAsync,
} from '../components';
import { GROUP_ORDER, groupColorVar, groupSlot, slotVar } from '../colors';
import { count } from '../format';

const UNGROUPED = 'UNGROUPED';
const UNGROUPED_LABEL = 'No listed research group';

function slotOf(code) {
  return code === UNGROUPED ? 'muted' : groupSlot(code);
}

export default function Coordinators() {
  const state = useAsync(() => api.coordinators(), []);
  return (
    <Section
      title="Coordinators"
      note="Counted by the coordinator role on each project, so a researcher listed only as a team member does not appear here. Colour splits each bar by the research group(s) that coordinator's own projects belong to."
    >
      <AsyncBoundary state={state}>
        {({ coordinators, group_names: groupNames }) => {
          const present = new Set();
          coordinators.forEach((row) => {
            Object.keys(row).forEach((key) => {
              if (key !== 'coordinator_slug' && key !== 'coordinator' && key !== 'project_count') {
                present.add(key);
              }
            });
          });
          const segmentKeys = [...GROUP_ORDER, UNGROUPED].filter((k) => present.has(k));
          const rows = coordinators.map((row) => {
            const filled = { ...row };
            segmentKeys.forEach((k) => {
              filled[k] = row[k] || 0;
            });
            return filled;
          });
          const labelOf = (code) => (code === UNGROUPED ? UNGROUPED_LABEL : groupNames[code] || code);

          return (
            <>
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
                  ...segmentKeys.map((k) => ({
                    key: k,
                    label: k === UNGROUPED ? 'Ungrouped' : k,
                    numeric: true,
                    render: (r) => count(r[k] || 0),
                  })),
                ]}
                rows={rows}
                getKey={(r) => r.coordinator_slug}
              >
                <StackedCategoryBars
                  data={rows}
                  categoryKey="coordinator"
                  segmentKeys={segmentKeys}
                  slotOf={slotOf}
                  valueFormat={count}
                  seriesLabelOf={labelOf}
                  categoryWidth={190}
                />
              </ChartWithTable>
              <GroupLegend
                groups={segmentKeys.map((code) => ({ code, name: labelOf(code) }))}
                colorOf={(g) => (g.code === UNGROUPED ? slotVar('muted') : groupColorVar(g.code))}
              />
            </>
          );
        }}
      </AsyncBoundary>
    </Section>
  );
}
