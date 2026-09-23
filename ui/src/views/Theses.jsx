// The Estudo Geral doctoral theses (S1), joined to the six CISUC research
// groups. Estudo Geral itself has no group field, so a thesis's group is
// derived from two independent signals (S7): where its author/supervisors
// work, and what its own text looks like against each group's projects.
//
// The tier is rendered, not just carried. A thesis whose two signals disagree
// shows both groups with a "contested" badge, and one resting on a single
// signal says so — because the failure this view was rebuilt to fix was not
// wrong groups, it was six equally-confident-looking ones. A name that does
// not resolve still stays visibly "(unattributed)" rather than being guessed,
// the same treatment "UNGROUPED" gets for projects in Coordinators.jsx.

import { api } from '../api';
import {
  AsyncBoundary,
  AttributionTier,
  Caveat,
  CategoryBars,
  ChartWithTable,
  GroupLegend,
  ResolvedPersonName,
  Section,
  Tile,
  useAsync,
} from '../components';
import { groupColorVar, groupSlot, slotVar } from '../colors';
import { count } from '../format';
import Search from './Search';

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
          <ResolvedPersonName person={p} title={p.note || undefined} />
          {p.status !== 'matched' ? (
            <span style={{ color: 'var(--text-muted)' }}> (unattributed)</span>
          ) : null}
        </span>
      ))}
    </>
  );
}

// `attribution.ranked` is rendered in preference to the sorted `groups` list:
// on a contested thesis the order is the point (people-signal candidate
// first), and a sorted list would throw it away. `groups` stays the fallback
// so an older payload still renders.
function GroupChips({ groups, attribution }) {
  const ranked = attribution?.ranked?.length
    ? attribution.ranked
    : groups.map((code) => ({ code }));
  if (!ranked.length) {
    return <span style={{ color: 'var(--text-muted)' }}>{UNATTRIBUTED_LABEL}</span>;
  }
  return (
    <span className="chips" style={{ alignItems: 'center' }}>
      {ranked.map((entry) => (
        <span
          key={entry.code}
          className="legend-item"
          title={
            entry.people_share === undefined
              ? undefined
              : `people signal ${(entry.people_share * 100).toFixed(0)}% of this thesis’s `
                + `people’s project history · text similarity ${entry.content_score.toFixed(3)}`
          }
        >
          <span className="swatch" style={{ background: groupColorVar(entry.code) }} />
          {entry.code}
        </span>
      ))}
      <AttributionTier tier={attribution?.tier} />
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
          const tiers = data.attribution_tiers || {};
          // The honest headline number: how many theses BOTH signals picked
          // the same group for. Leading with "resolved to a group" alone is
          // what let 35 theses tagged with all six look like a success.
          const corroborated = tiers.corroborated || 0;
          const singleSignal = (tiers['people-only'] || 0) + (tiers['content-only'] || 0);
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
                <Tile
                  value={count(corroborated)}
                  label="Corroborated by both signals"
                  note={
                    [
                      tiers.contested ? `${count(tiers.contested)} contested` : null,
                      singleSignal ? `${count(singleSignal)} on one signal only` : null,
                    ]
                      .filter(Boolean)
                      .join(' · ') || undefined
                  }
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
                      <Caveat label="At most two groups per thesis">{g.caveat}</Caveat>
                      <ChartWithTable
                        title="Theses per research group"
                        note="Source: /api/theses/groups — a thesis counts towards one group where its people signal and its text agree, and towards both where they do not."
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

              <Search onOpenThesis={onOpenThesis} />

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
                            <GroupChips groups={t.groups} attribution={t.group_attribution} />
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
