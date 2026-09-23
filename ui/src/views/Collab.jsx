// Collaboration & teams — who works with whom (co_project) and who
// co-supervises (co_supervision). Ranked table + person-anchored
// neighbourhood, deliberately never a raw node-link graph: 4,242 edges over
// 475 people drawn without an anchor is a hairball, not an answer.

import { useEffect, useState } from 'react';
import { api } from '../api';
import { AsyncBoundary, Caveat, DataTable, Section, Tile, useAsync } from '../components';
import { groupColorVar } from '../colors';
import { count } from '../format';

const PAGE_SIZE = 50;
const KIND_LABEL = { co_project: 'Co-project', co_supervision: 'Co-supervision' };
const FLOOR_OPTIONS = [1, 2, 3, 5];

function GroupChips({ groups }) {
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
          onClick={() => onChange(n)}
        >
          ≥{n}
        </button>
      ))}
    </div>
  );
}

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
        placeholder="Anchor on a person — search a name…"
        aria-label="Search a person to anchor the graph on"
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
              { key: 'person_a', label: 'Person' },
              { key: 'person_a_groups', label: 'Groups', render: (r) => <GroupChips groups={r.person_a_groups} /> },
              { key: 'person_b', label: 'Person' },
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

function PersonNeighbourhood({ anchor, kind, minWeight, onClear }) {
  const state = useAsync(() => api.collabPerson(anchor.slug, { kind, minWeight }), [anchor.slug, kind, minWeight]);

  return (
    <AsyncBoundary state={state}>
      {(data) => (
        <div className="card">
          <p className="chart-note">
            <strong>{data.person.name}</strong>
            {' — '}
            <GroupChips groups={data.person.groups} />
            {' · '}
            {count(data.total)} collaborator(s) at ≥{data.min_weight}{' '}
            {kind === 'co_project' ? 'shared project(s)' : 'shared thesis/theses'}
            {' · '}
            <button type="button" className="link-button" onClick={onClear}>
              Clear anchor
            </button>
          </p>
          <DataTable
            columns={[
              { key: 'name', label: 'Collaborator' },
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

const DEFAULT_FLOOR = { co_project: 2, co_supervision: 1 };

export default function Collab() {
  const summaryState = useAsync(() => api.collabSummary(), []);
  const [kind, setKind] = useState('co_project');
  const [minWeight, setMinWeight] = useState(DEFAULT_FLOOR.co_project);
  const [anchor, setAnchor] = useState(null);

  const changeKind = (next) => {
    setKind(next);
    setMinWeight(DEFAULT_FLOOR[next]);
  };

  return (
    <Section
      title="Collaboration & teams"
      note="Who works with whom, derived from data already in the seed — 4,242 co-project pairs and 21 co-supervision pairs, zero new scraping. Two edge kinds, kept separate and never summed: sharing a project is not the same fact as co-supervising a thesis."
    >
      <AsyncBoundary state={summaryState}>
        {(summary) => (
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
        )}
      </AsyncBoundary>

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

      <FloorPicker kind={kind} value={minWeight} onChange={setMinWeight} />

      <AnchorPicker onSelect={setAnchor} />

      {anchor ? (
        <PersonNeighbourhood anchor={anchor} kind={kind} minWeight={minWeight} onClear={() => setAnchor(null)} />
      ) : (
        <PairsTable kind={kind} minWeight={minWeight} />
      )}
    </Section>
  );
}
