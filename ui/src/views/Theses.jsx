// The 18 Estudo Geral doctoral theses (S1), joined to the six CISUC research
// groups (S5's own hand-verified people join — see
// docs/thesis-attribution.md). Estudo Geral itself has no group field, so a
// thesis's group(s) come from its author's/supervisors' own project history,
// and a name that does not exactly resolve stays visibly "Unattributed"
// rather than being guessed — same treatment "UNGROUPED" gets for projects
// in Coordinators.jsx.

import { api } from '../api';
import {
  AsyncBoundary,
  Caveat,
  CategoryBars,
  ChartWithTable,
  GroupLegend,
  Section,
  Tile,
  useAsync,
} from '../components';
import { groupColorVar, groupSlot, slotVar } from '../colors';
import { count } from '../format';

const UNATTRIBUTED = 'UNATTRIBUTED';
const UNATTRIBUTED_LABEL = 'Unattributed';

function slotOf(code) {
  return code === UNATTRIBUTED ? 'muted' : groupSlot(code);
}

function PersonList({ people }) {
  if (!people.length) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  return (
    <>
      {people.map((p, i) => (
        <span key={p.name}>
          {i > 0 ? ', ' : ''}
          <span title={p.note || undefined}>{p.name}</span>
          {p.status !== 'matched' ? (
            <span style={{ color: 'var(--text-muted)' }}> (unattributed)</span>
          ) : null}
        </span>
      ))}
    </>
  );
}

function GroupChips({ groups }) {
  if (!groups.length) {
    return <span style={{ color: 'var(--text-muted)' }}>{UNATTRIBUTED_LABEL}</span>;
  }
  return (
    <span className="chips">
      {groups.map((g) => (
        <span key={g} className="legend-item">
          <span className="swatch" style={{ background: groupColorVar(g) }} />
          {g}
        </span>
      ))}
    </span>
  );
}

export default function Theses({ onOpenThesis }) {
  const listState = useAsync(() => api.theses(), []);
  const groupsState = useAsync(() => api.thesesGroups(), []);

  return (
    <Section
      title="Theses (Estudo Geral)"
      note="Every DEI doctoral thesis extracted from Estudo Geral, joined to CISUC research groups by hand-verified author/supervisor identity — not from Estudo Geral itself, which publishes no research-group field."
    >
      <AsyncBoundary state={listState}>
        {(data) => {
          const total = data.theses.length;
          const fullText = data.theses.filter((t) => t.full_text).length;
          const attributed = data.theses.filter((t) => t.attributed).length;
          return (
            <>
              <div className="tiles">
                <Tile value={count(total)} label="Theses" />
                <Tile
                  value={count(fullText)}
                  label="Full text indexed"
                  note={total - fullText ? `${count(total - fullText)} metadata-only (embargoed)` : undefined}
                />
                <Tile
                  value={count(attributed)}
                  label="Resolved to a research group"
                  note={total - attributed ? `${count(total - attributed)} unattributed` : undefined}
                />
              </div>

              <AsyncBoundary state={groupsState}>
                {(g) => {
                  const rows = [
                    ...g.groups,
                    ...(g.unattributed
                      ? [{ code: UNATTRIBUTED, name: UNATTRIBUTED_LABEL, thesis_count: g.unattributed }]
                      : []),
                  ];
                  return (
                    <>
                      <Caveat label="Many-to-many, and hand-verified">{g.caveat}</Caveat>
                      <ChartWithTable
                        title="Theses per research group"
                        note="Source: /api/theses/groups — a thesis's group is the union of its author's and supervisors' own groups."
                        columns={[
                          { key: 'code', label: 'Group' },
                          { key: 'name', label: 'Name' },
                          {
                            key: 'thesis_count',
                            label: 'Theses',
                            numeric: true,
                            render: (r) => count(r.thesis_count),
                          },
                        ]}
                        rows={rows}
                        getKey={(r) => r.code}
                      >
                        <CategoryBars
                          data={rows}
                          categoryKey="code"
                          valueKey="thesis_count"
                          slotOf={(d) => slotOf(d.code)}
                          valueFormat={count}
                          seriesLabel="Theses"
                          categoryWidth={90}
                          height={220}
                        />
                      </ChartWithTable>
                      <GroupLegend
                        groups={rows.map((r) => ({ code: r.code, name: r.name }))}
                        colorOf={(r) => (r.code === UNATTRIBUTED ? slotVar('muted') : groupColorVar(r.code))}
                      />
                    </>
                  );
                }}
              </AsyncBoundary>

              <Caveat label="How names are resolved">{data.attribution_note}</Caveat>

              <div className="card">
                <p className="chart-title">All {count(total)} theses</p>
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th scope="col">Title</th>
                        <th scope="col">Author</th>
                        <th scope="col">Supervisor(s)</th>
                        <th scope="col">Year</th>
                        <th scope="col">Research group(s)</th>
                        <th scope="col">Full text</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.theses.map((t) => (
                        <tr key={t.handle}>
                          <td>
                            <button
                              type="button"
                              className="link-button"
                              onClick={() => onOpenThesis(t.handle)}
                            >
                              {t.title}
                            </button>
                          </td>
                          <td>
                            <PersonList people={t.authors} />
                          </td>
                          <td>
                            <PersonList people={t.supervisors} />
                          </td>
                          <td>{t.year || '—'}</td>
                          <td>
                            <GroupChips groups={t.groups} />
                          </td>
                          <td>
                            {t.full_text ? (
                              'Indexed'
                            ) : (
                              <span style={{ color: 'var(--text-muted)' }}>
                                Metadata only{t.rights === 'embargoedAccess' ? ' (embargoed)' : ''}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          );
        }}
      </AsyncBoundary>
    </Section>
  );
}
