// Collaboration & teams — who works with whom (co_project) and who
// co-supervises (co_supervision). Ranked table, person-anchored
// neighbourhood, and — since the floor makes it an answer rather than a
// hairball — a filtered node-link graph (CollabGraph.jsx) drawn above both.
// Floor 1 still draws the full 4,242-edge tangle, on purpose: seeing it is a
// better argument for the floor than this comment.

import { useEffect, useState } from 'react';
import { api } from '../api';
import { AsyncBoundary, Caveat, DataTable, PersonLink, Section, Tile, useAsync } from '../components';
import { groupColorVar } from '../colors';
import { count } from '../format';
import CollabGraph from './CollabGraph';

const PAGE_SIZE = 50;
const KIND_LABEL = { co_project: 'Co-project', co_supervision: 'Co-supervision' };
const FLOOR_OPTIONS = [1, 2, 3, 4, 5];

export function GroupChips({ groups }) {
  if (!groups || !groups.length) return <span className="chart-note">—</span>;
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

function CrossGroupCell({ value }) {
  if (value == null) return <span className="chart-note">unknown</span>;
  return value ? 'yes' : 'no';
}

function FloorPicker({ kind, value, onChange }) {
  const pinned = kind === 'co_supervision';
  return (
    <div className="group-pills">
      <span className="chart-note">
        Minimum shared {kind === 'co_project' ? 'projects' : 'theses'}:
      </span>
      {FLOOR_OPTIONS.map((n) => (
        <button
          key={n}
          type="button"
          className="group-pill"
          aria-pressed={value === n}
          disabled={pinned}
          onClick={() => onChange(n)}
        >
          ≥{n}
        </button>
      ))}
      {pinned ? (
        <span className="chart-note">
          Pinned at ≥1 — 49 of 53 co-supervision pairs share exactly one thesis, so ≥2 leaves a
          degenerate 4-edge graph, not a network.
        </span>
      ) : null}
    </div>
  );
}

/** Person search stays server-backed, deliberately: it reaches all 470
 *  people, and at the default floor only 91 of them are drawn. Picking
 *  someone the graph does not contain is a legitimate outcome — CollabGraph
 *  says so in words rather than dimming itself to nothing. */
function AnchorPicker({ onSelect }) {
  const [input, setInput] = useState('');
  const [q, setQ] = useState('');

  useEffect(() => {
    const t = setTimeout(() => setQ(input.trim()), 250);
    return () => clearTimeout(t);
  }, [input]);

  const state = useAsync(() => api.collabPeople({ q: q || undefined, limit: q ? 20 : 8 }), [q]);

  return (
    <div className="filters">
      <input
        type="search"
        value={input}
        placeholder="Focus on a person — search a name…"
        aria-label="Search a person to focus the graph on"
        onChange={(e) => setInput(e.target.value)}
      />
      <AsyncBoundary state={state}>
        {(data) => (
          <span className="chips">
            {data.people.map((p) => (
              <button
                key={p.slug}
                type="button"
                className="link-button"
                onClick={() => onSelect(p)}
                title={`${count(p.project_count)} projects`}
              >
                {p.name}
              </button>
            ))}
            {!data.people.length ? <span className="chart-note">No match</span> : null}
          </span>
        )}
      </AsyncBoundary>
    </div>
  );
}

function PairsTable({ kind, minWeight }) {
  const [offset, setOffset] = useState(0);
  const state = useAsync(
    () => api.collabPairs({ kind, minWeight, limit: PAGE_SIZE, offset }),
    [kind, minWeight, offset],
  );

  return (
    <AsyncBoundary state={state}>
      {(data) => (
        <div className="card">
          <p className="chart-note">
            {count(data.total)} pairs with at least {data.min_weight} shared{' '}
            {kind === 'co_project' ? 'project(s)' : 'thesis/theses'}
          </p>
          <DataTable
            columns={[
              { key: 'person_a', label: 'Person', render: (r) => <PersonLink slug={r.person_a_slug}>{r.person_a}</PersonLink> },
              { key: 'person_a_groups', label: 'Groups', render: (r) => <GroupChips groups={r.person_a_groups} /> },
              { key: 'person_b', label: 'Person', render: (r) => <PersonLink slug={r.person_b_slug}>{r.person_b}</PersonLink> },
              { key: 'person_b_groups', label: 'Groups', render: (r) => <GroupChips groups={r.person_b_groups} /> },
              { key: 'weight', label: 'Weight', numeric: true, render: (r) => count(r.weight) },
              ...(kind === 'co_project'
                ? [{ key: 'weight_normalized', label: 'Weight (size-normalised)', numeric: true, render: (r) => r.weight_normalized }]
                : []),
              { key: 'cross_group', label: 'Different groups?', render: (r) => <CrossGroupCell value={r.cross_group} /> },
            ]}
            rows={data.pairs}
            getKey={(r) => `${r.person_a_slug}-${r.person_b_slug}`}
          />
          <div className="pager">
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              ← Previous
            </button>
            <span className="pager-status">
              {data.total === 0
                ? 'No results'
                : `${offset + 1}–${Math.min(offset + PAGE_SIZE, data.total)} of ${count(data.total)}`}
            </span>
            <button type="button" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>
              Next →
            </button>
          </div>
          <Caveat>{data.caveat}</Caveat>
          <Caveat label="cross_group">{data.cross_group_caveat}</Caveat>
        </div>
      )}
    </AsyncBoundary>
  );
}

/** The graph's detail panel as well as the table's — it is driven by the one
 *  `focus` below, so clicking a circle and picking a name from search now
 *  land in the same place. It lives OUTSIDE CollabGraph on purpose: its
 *  fetch resolving re-renders only itself, and a re-render inside the graph
 *  mid-drag would snap the node being dragged back to its last position. */
function PersonNeighbourhood({ anchor, kind, minWeight, onClear }) {
  const state = useAsync(() => api.collabPerson(anchor.slug, { kind, minWeight }), [anchor.slug, kind, minWeight]);

  return (
    <AsyncBoundary state={state}>
      {(data) => (
        <div className="card">
          <p className="chart-note">
            <strong>
              <PersonLink slug={data.person.slug}>{data.person.name}</PersonLink>
            </strong>
            {' — '}
            <GroupChips groups={data.person.groups} />
            {' · '}
            {count(data.total)} collaborator(s) at ≥{data.min_weight}{' '}
            {kind === 'co_project' ? 'shared project(s)' : 'shared thesis/theses'}
            {' · '}
            <button type="button" className="link-button" onClick={onClear}>
              Clear focus
            </button>
          </p>
          <DataTable
            columns={[
              { key: 'name', label: 'Collaborator', render: (r) => <PersonLink slug={r.slug}>{r.name}</PersonLink> },
              { key: 'groups', label: 'Groups', render: (r) => <GroupChips groups={r.groups} /> },
              { key: 'weight', label: 'Weight', numeric: true, render: (r) => count(r.weight) },
              ...(kind === 'co_project'
                ? [{ key: 'weight_normalized', label: 'Weight (size-normalised)', numeric: true, render: (r) => r.weight_normalized }]
                : []),
              { key: 'cross_group', label: 'Different groups?', render: (r) => <CrossGroupCell value={r.cross_group} /> },
            ]}
            rows={data.collaborators}
            getKey={(r) => r.slug}
          />
          <Caveat>{data.caveat}</Caveat>
          <Caveat label="cross_group">{data.cross_group_caveat}</Caveat>
        </div>
      )}
    </AsyncBoundary>
  );
}

export default function Collab() {
  const summaryState = useAsync(() => api.collabSummary(), []);
  const [kind, setKind] = useState('co_project');
  // null until a floor is explicitly picked — the effective floor is seeded
  // from /collab/summary's graph_min_weight below, once it resolves. One
  // fetch, one source of truth: no correcting effect, so no double fetch of
  // pairs/graph on mount.
  const [minWeight, setMinWeight] = useState(null);
  // ONE selection for the whole section. Until now the table had an `anchor`
  // the graph could not see and the graph had a `selectedSlug` the table
  // could not see — two selection concepts for one question ("show me this
  // person"). Clicking a circle and searching a name are the same act, so
  // they write the same state, and PersonNeighbourhood answers both.
  const [focus, setFocus] = useState(null);

  const changeKind = (next) => {
    setKind(next);
    setMinWeight(null);
  };

  return (
    <Section
      title="Collaboration & teams"
      note="Who works with whom, derived from data already in the seed — 4,242 co-project pairs and 53 co-supervision pairs, zero new scraping. Two edge kinds, kept separate and never summed: sharing a project is not the same fact as co-supervising a thesis."
    >
      <AsyncBoundary state={summaryState}>
        {(summary) => {
          const floor = minWeight ?? summary.graph_min_weight[kind];
          return (
            <>
              <div className="tiles">
                <Tile value={count(summary.total_people)} label="People" />
                <Tile value={count(summary.people_on_multiple_projects)} label="On 2+ projects" />
                <Tile
                  value={count(summary.co_project.pair_count)}
                  label="Co-project pairs"
                  note={`${count(summary.co_project.pairs_below_floor)} share exactly 1 project`}
                />
                <Tile
                  value={count(summary.co_supervision.pair_count)}
                  label="Co-supervision pairs"
                  note={`max ${count(summary.co_supervision.max_weight)} shared theses`}
                />
              </div>

              <div className="group-pills">
                {Object.entries(KIND_LABEL).map(([k, label]) => (
                  <button
                    key={k}
                    type="button"
                    className="group-pill"
                    aria-pressed={kind === k}
                    onClick={() => changeKind(k)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <FloorPicker kind={kind} value={floor} onChange={setMinWeight} />

              <AnchorPicker onSelect={setFocus} />

              <CollabGraph kind={kind} minWeight={floor} focus={focus} onFocus={setFocus} />

              {focus ? (
                <PersonNeighbourhood anchor={focus} kind={kind} minWeight={floor} onClear={() => setFocus(null)} />
              ) : (
                <PairsTable kind={kind} minWeight={floor} />
              )}
            </>
          );
        }}
      </AsyncBoundary>
    </Section>
  );
}
