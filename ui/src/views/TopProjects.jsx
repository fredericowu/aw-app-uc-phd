// Top 10 projects per research group, all six groups.
//
// The ranking metric is a documented proxy, not a given — the API returns that
// caveat with the data and it is rendered above the tables, unconditionally.
// A reader who scrolls straight to a table still sees it.

import { api } from '../api';
import {
  AsyncBoundary,
  Caveat,
  DataTable,
  ExternalLink,
  Section,
  useAsync,
} from '../components';
import { groupColorVar } from '../colors';
import { money, truncate } from '../format';

function GroupTable({ group, onOpen }) {
  return (
    <div className="card">
      <p className="chart-title">
        <span
          className="swatch"
          style={{
            background: groupColorVar(group.code),
            display: 'inline-block',
            width: 10,
            height: 10,
            borderRadius: 2,
            marginRight: 8,
          }}
        />
        {group.code} — {group.name}
      </p>
      <p className="chart-note">{group.projects.length} projects shown, ranked by total budget</p>
      <DataTable
        columns={[
          { key: 'rank_in_group', label: '#', numeric: true },
          {
            key: 'title',
            label: 'Project',
            render: (r) => (
              <>
                <button type="button" className="link-button" onClick={() => onOpen(r.project_id)}>
                  {r.title}
                </button>
                {r.detail_url ? (
                  <>
                    {' '}
                    <ExternalLink href={r.detail_url} title="Open on cisuc.uc.pt" />
                  </>
                ) : null}
                <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                  {truncate(r.synopsis, 160)}
                </div>
              </>
            ),
          },
          {
            key: 'total_budget_amount',
            label: 'Total budget',
            numeric: true,
            render: (r) => money(r.total_budget_amount),
          },
        ]}
        rows={group.projects}
        getKey={(r) => r.project_id}
      />
    </div>
  );
}

export default function TopProjects({ onOpenProject }) {
  const state = useAsync(() => api.topProjects(), []);
  return (
    <Section
      title="Top 10 projects per research group"
      note="Every group's ten largest projects, each linking to its page on cisuc.uc.pt."
    >
      <AsyncBoundary state={state}>
        {(data) => (
          <>
            <Caveat label="The ranking is a proxy">{data.caveat}</Caveat>
            <div className="grid">
              {data.groups.map((g) => (
                <GroupTable key={g.code} group={g} onOpen={onOpenProject} />
              ))}
            </div>
          </>
        )}
      </AsyncBoundary>
    </Section>
  );
}
