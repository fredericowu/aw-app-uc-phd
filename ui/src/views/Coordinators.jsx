// Who coordinates the most projects, split by which research group(s) their
// projects belong to — colour carries group identity, same as every other
// per-group chart in this app.

import { useState } from 'react';
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
  // Click a legend entry to toggle it into/out of the filter; empty selection
  // means "show every group", never an empty chart.
  const [selected, setSelected] = useState(() => new Set());
  const toggleGroup = (code) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  return (
    <Section
      title="Coordinators"
      note="Counted by the coordinator role on each project, so a researcher listed only as a team member does not appear here. Colour splits each bar by the research group(s) that coordinator's own projects belong to. Click a group in the legend to show only that group (or group combination) — click again to clear it."
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

          const activeKeys = selected.size ? segmentKeys.filter((k) => selected.has(k)) : segmentKeys;
          const visibleRows = selected.size
            ? rows.filter((r) => activeKeys.some((k) => r[k] > 0))
            : rows;

          return (
            <>
              <GroupLegend
                groups={segmentKeys.map((code) => ({ code, name: labelOf(code) }))}
                colorOf={(g) => (g.code === UNGROUPED ? slotVar('muted') : groupColorVar(g.code))}
                selected={selected}
                onToggle={toggleGroup}
              />
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
                  ...activeKeys.map((k) => ({
                    key: k,
                    label: k === UNGROUPED ? 'Ungrouped' : k,
                    numeric: true,
                    render: (r) => count(r[k] || 0),
                  })),
                ]}
                rows={visibleRows}
                getKey={(r) => r.coordinator_slug}
              >
                <StackedCategoryBars
                  data={visibleRows}
                  categoryKey="coordinator"
                  segmentKeys={activeKeys}
                  slotOf={slotOf}
                  valueFormat={count}
                  seriesLabelOf={labelOf}
                  categoryWidth={190}
                />
              </ChartWithTable>
            </>
          );
        }}
      </AsyncBoundary>
    </Section>
  );
}
