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

import { useMemo, useState } from 'react';
import { api } from '../api';
import {
  AsyncBoundary,
  AttributionTier,
  Caveat,
  CategoryBars,
  ChartWithTable,
  DataTable,
  ExternalIdentity,
  GroupLegend,
  ResolvedPersonName,
  SearchMultiSelect,
  Section,
  Tile,
  useAsync,
} from '../components';
import { GROUP_ORDER, groupColorVar, groupSlot, slotVar } from '../colors';
import { count } from '../format';
import { UNATTRIBUTED, filterTheses, personKey, sortTheses } from '../thesesTable';
import Search from './Search';

const UNATTRIBUTED_LABEL = 'Unattributed';

function toggleInSet(prev, value) {
  const next = new Set(prev);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

// Click cycles asc -> desc -> none (none = original API order).
function cycleSort(key, prev) {
  if (prev.key !== key) return { key, dir: 'asc' };
  if (prev.dir === 'asc') return { key, dir: 'desc' };
  if (prev.dir === 'desc') return { key: null, dir: null };
  return { key, dir: 'asc' };
}

function SortableTh({ label, sortKey, sort, onSort }) {
  const active = sort.key === sortKey;
  return (
    <th scope="col" aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" className="th-sort" onClick={() => onSort(sortKey)}>
        {label}
        {active ? <span aria-hidden="true"> {sort.dir === 'asc' ? '▲' : '▼'}</span> : null}
      </button>
    </th>
  );
}

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
          {/* A researched external identity replaces the bare label rather
              than joining it: "(unattributed) — Torsten Braun (external)"
              would read as a defect beside the answer to it. The bare label
              stays for every name nobody has looked up — the 4 ambiguous
              ones and Álvaro Rocha, who is a real CISUC person missing from
              the directory snapshot and therefore gets no external entry. */}
          {p.status !== 'matched' ? (
            p.external ? (
              <ExternalIdentity external={p.external} compact />
            ) : (
              <span style={{ color: 'var(--text-muted)' }}> (unattributed)</span>
            )
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

// The supervisor side at the EDGE grain, which is what the advisor and
// collaboration views actually consume — a supervisor on ten theses is ten
// advisor edges, so the name-grain number understates what one failure costs.
// Deliberately not the pooled 283-name figure: that one mixes in the authors,
// a third of whom correctly do not resolve.
function IdentityTile({ identity }) {
  const edges = identity.supervision_edges;
  return (
    <Tile
      value={edges.total ? `${Math.round((100 * edges.resolved) / edges.total)}%` : '—'}
      label="Supervisor names resolved to a person"
      note={
        `${count(edges.resolved)} of ${count(edges.total)} supervision edges · `
        + `${count(identity.supervisor_people)} distinct supervisors`
      }
    />
  );
}

// The rest of the grains, as numbers rather than as an adjective. Every figure
// comes off the payload: the version of this text that hardcoded "a handful"
// was written at 18 theses and was still on screen at 181.
function IdentitySentence({ identity }) {
  const sup = identity.names.supervisor;
  const author = identity.names.author;
  const th = identity.theses;
  const pairs = identity.co_supervision_pairs;
  return (
    <>
      {count(sup.total - sup.resolved)} of {count(sup.total)} distinct supervisor names do not
      resolve, so {count(th.with_a_resolved_supervisor)} of {count(th.listing_a_supervisor)} theses
      that name a supervisor have at least one resolved and {count(th.fully_resolved)} have all of
      them; {count(pairs.total - pairs.resolved)} of {count(pairs.total)} co-supervision pairs are
      lost with them. {count(author.total - author.resolved)} of {count(author.total)} author names
      are unresolved, which is expected rather than a gap.{' '}
      {count(th.total - th.listing_a_supervisor)} of {count(th.total)} theses name no supervisor at
      all in their metadata — an extraction gap, not a matching one, and counted separately here for
      that reason.
    </>
  );
}

// The theses behind the "Resolved to a research group" tile's small
// "unattributed" count — already loaded in `data.theses` (the `attributed`
// computation this mirrors lives where the tile's own numbers are built),
// so expanding costs no extra request.
function UnattributedTheses({ theses, onOpenThesis }) {
  const rows = theses.filter((t) => !t.attributed);
  return (
    <DataTable
      columns={[
        {
          key: 'title',
          label: 'Title',
          render: (t) => (
            <button type="button" className="link-button" onClick={() => onOpenThesis(t.handle)}>
              {t.title}
            </button>
          ),
        },
      ]}
      rows={rows}
      getKey={(t) => t.handle}
    />
  );
}

export default function Theses({ onOpenThesis }) {
  const listState = useAsync(() => api.theses(), []);
  const groupsState = useAsync(() => api.thesesGroups(), []);
  const [showUnattributed, setShowUnattributed] = useState(false);

  // Sort/filter state for the big table — local, not URL (no view in this
  // app puts filter state in the URL; see Projects.jsx). `data.theses`
  // arrives whole (~181 rows, no pagination), so every bit of this is a
  // client-side array operation on a COPY, never a mutation of the source.
  const [sort, setSort] = useState({ key: null, dir: null });
  const [selectedGroups, setSelectedGroups] = useState(() => new Set());
  const [selectedAuthors, setSelectedAuthors] = useState(() => new Set());
  const onSort = (key) => setSort((prev) => cycleSort(key, prev));

  const authorOptions = useMemo(() => {
    if (!listState.data) return [];
    const byKey = new Map();
    for (const t of listState.data.theses) {
      for (const p of t.authors) {
        const key = personKey(p);
        if (!byKey.has(key)) byKey.set(key, { key, label: p.name });
      }
    }
    return [...byKey.values()].sort((a, b) =>
      a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }),
    );
  }, [listState.data]);

  const visibleTheses = useMemo(() => {
    if (!listState.data) return [];
    const filtered = filterTheses(listState.data.theses, {
      groups: selectedGroups,
      authorKeys: selectedAuthors,
    });
    return sortTheses(filtered, sort);
  }, [listState.data, selectedGroups, selectedAuthors, sort]);

  const hasFilters = selectedGroups.size > 0 || selectedAuthors.size > 0;
  const hasSort = Boolean(sort.key && sort.dir);

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
          // How far the name -> person spine reaches. Until this card it was
          // computed, shipped on /api/theses, and rendered NOWHERE — which is
          // the "silently omit the gap" outcome this view was supposed to
          // avoid. Optional so an older payload still renders.
          const identity = data.identity_coverage;
          return (
            <>
              <div className="tiles">
                <Tile value={count(total)} label="Theses" />
                <Tile
                  value={count(fullText)}
                  label="Full text indexed"
                  note={total - fullText ? `${count(total - fullText)} metadata-only (embargoed)` : undefined}
                />
                <div className="tile">
                  <div className="tile-value">{count(attributed)}</div>
                  <div className="tile-label">Resolved to a research group</div>
                  {total - attributed ? (
                    <>
                      <div className="tile-note">{count(total - attributed)} unattributed</div>
                      <button
                        type="button"
                        className="table-toggle"
                        aria-expanded={showUnattributed}
                        onClick={() => setShowUnattributed((v) => !v)}
                      >
                        {showUnattributed ? 'Show fewer' : `+ ${count(total - attributed)} more`}
                      </button>
                    </>
                  ) : null}
                </div>
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
                {identity ? <IdentityTile identity={identity} /> : null}
              </div>

              {showUnattributed ? (
                <UnattributedTheses theses={data.theses} onOpenThesis={onOpenThesis} />
              ) : null}

              <Search onOpenThesis={onOpenThesis} />

              {identity ? (
                <Caveat label="Identity coverage">
                  <IdentitySentence identity={identity} /> {data.identity_note}
                </Caveat>
              ) : null}

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

              <div className="card">
                <p className="chart-title">
                  {hasFilters || hasSort
                    ? `${count(visibleTheses.length)} of ${count(total)} theses`
                    : `All ${count(total)} theses`}
                </p>

                <div className="group-pills">
                  <button
                    type="button"
                    className="group-pill"
                    aria-pressed={selectedGroups.size === 0}
                    onClick={() => setSelectedGroups(new Set())}
                  >
                    All groups
                  </button>
                  {GROUP_ORDER.map((code) => (
                    <button
                      key={code}
                      type="button"
                      className="group-pill"
                      aria-pressed={selectedGroups.has(code)}
                      onClick={() => setSelectedGroups((s) => toggleInSet(s, code))}
                    >
                      <span className="swatch" style={{ background: groupColorVar(code) }} />
                      {code}
                    </button>
                  ))}
                  <button
                    type="button"
                    className="group-pill"
                    aria-pressed={selectedGroups.has(UNATTRIBUTED)}
                    onClick={() => setSelectedGroups((s) => toggleInSet(s, UNATTRIBUTED))}
                  >
                    <span className="swatch" style={{ background: slotVar('muted') }} />
                    {UNATTRIBUTED_LABEL}
                  </button>
                </div>

                <SearchMultiSelect
                  options={authorOptions}
                  selected={selectedAuthors}
                  onToggle={(key) => setSelectedAuthors((s) => toggleInSet(s, key))}
                  placeholder="Filter by author…"
                />

                {hasFilters || hasSort ? (
                  <button
                    type="button"
                    className="table-toggle"
                    onClick={() => {
                      setSelectedGroups(new Set());
                      setSelectedAuthors(new Set());
                      setSort({ key: null, dir: null });
                    }}
                  >
                    Clear filters
                  </button>
                ) : null}

                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <SortableTh label="Title" sortKey="title" sort={sort} onSort={onSort} />
                        <SortableTh label="Author" sortKey="author" sort={sort} onSort={onSort} />
                        <SortableTh
                          label="Supervisor(s)"
                          sortKey="supervisors"
                          sort={sort}
                          onSort={onSort}
                        />
                        <SortableTh label="Year" sortKey="year" sort={sort} onSort={onSort} />
                        <SortableTh
                          label="Research group(s)"
                          sortKey="group"
                          sort={sort}
                          onSort={onSort}
                        />
                        <SortableTh
                          label="Full text"
                          sortKey="full_text"
                          sort={sort}
                          onSort={onSort}
                        />
                      </tr>
                    </thead>
                    <tbody>
                      {visibleTheses.length === 0 ? (
                        <tr>
                          <td colSpan={6} style={{ color: 'var(--text-muted)' }}>
                            No theses match
                          </td>
                        </tr>
                      ) : (
                        visibleTheses.map((t) => (
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
                        ))
                      )}
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
