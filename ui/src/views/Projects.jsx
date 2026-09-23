// The searchable catalogue — the first of the two things the static
// presentation could never do. Filters sit in one row above the results.

import { useEffect, useState } from 'react';
import { api } from '../api';
import { AsyncBoundary, DataTable, Section, useAsync } from '../components';
import { GROUP_ORDER, groupColorVar } from '../colors';
import { count, date, money, truncate } from '../format';

const PAGE_SIZE = 50;

export default function Projects({ onOpenProject }) {
  const [input, setInput] = useState('');
  const [q, setQ] = useState('');
  const [group, setGroup] = useState(null);
  const [offset, setOffset] = useState(0);

  // Debounce the search box so every keystroke isn't a request.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(input.trim());
      setOffset(0);
    }, 250);
    return () => clearTimeout(t);
  }, [input]);

  const state = useAsync(
    () => api.projects({ group, q: q || undefined, limit: PAGE_SIZE, offset }),
    [group, q, offset],
  );

  return (
    <Section
      title="All projects"
      note="Every project in the database, searchable by title and filterable by research group. Open one for its full record."
    >
      <div className="filters">
        <input
          type="search"
          value={input}
          placeholder="Search project titles…"
          aria-label="Search project titles"
          onChange={(e) => setInput(e.target.value)}
        />
      </div>

      <div className="group-pills">
        <button
          type="button"
          className="group-pill"
          aria-pressed={group === null}
          onClick={() => {
            setGroup(null);
            setOffset(0);
          }}
        >
          All groups
        </button>
        {GROUP_ORDER.map((code) => (
          <button
            key={code}
            type="button"
            className="group-pill"
            aria-pressed={group === code}
            onClick={() => {
              setGroup(group === code ? null : code);
              setOffset(0);
            }}
          >
            <span className="swatch" style={{ background: groupColorVar(code) }} />
            {code}
          </button>
        ))}
      </div>

      <AsyncBoundary state={state}>
        {(data) => (
          <div className="card">
            <p className="chart-note">
              {count(data.total)} {data.total === 1 ? 'project' : 'projects'} match
              {group ? ` in ${group}` : ''}
              {q ? ` for “${q}”` : ''}
            </p>
            <DataTable
              columns={[
                {
                  key: 'title',
                  label: 'Project',
                  render: (r) => (
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onOpenProject(r.id)}
                    >
                      {truncate(r.title, 110)}
                    </button>
                  ),
                },
                {
                  key: 'groups',
                  label: 'Groups',
                  render: (r) => (
                    <span className="chips">
                      {r.groups.map((g) => (
                        <span key={g} className="legend-item">
                          <span className="swatch" style={{ background: groupColorVar(g) }} />
                          {g}
                        </span>
                      ))}
                    </span>
                  ),
                },
                { key: 'scope', label: 'Scope', render: (r) => r.scope || '—' },
                { key: 'start_date', label: 'Start', render: (r) => date(r.start_date) },
                {
                  key: 'total_budget_amount',
                  label: 'Total budget',
                  numeric: true,
                  render: (r) => money(r.total_budget_amount),
                },
              ]}
              rows={data.projects}
              getKey={(r) => r.id}
            />
            <div className="pager">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                ← Previous
              </button>
              <span className="pager-status">
                {data.total === 0
                  ? 'No results'
                  : `${offset + 1}–${Math.min(offset + PAGE_SIZE, data.total)} of ${count(data.total)}`}
              </span>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next →
              </button>
            </div>
          </div>
        )}
      </AsyncBoundary>
    </Section>
  );
}
