// Partners — the site's free-text Partners field, parsed into a
// project_partners table and flagged academic vs industry by a keyword
// heuristic (scraper/parse.py:classify_partner). A partner is not a
// funder: this is who CISUC worked with, not who paid — see the caveat
// the API carries with every payload below.

import { useState } from 'react';
import { api } from '../api';
import {
  AsyncBoundary,
  Caveat,
  CategoryBars,
  ChartWithTable,
  Section,
  Tile,
  useAsync,
} from '../components';
import { partnerTypeColorVar, partnerTypeSlot } from '../colors';
import { count, truncate } from '../format';

const TYPE_LABEL = { academic: 'Academic', industry: 'Industry' };
const TYPES = ['academic', 'industry'];

export default function Partners() {
  const state = useAsync(() => api.partners(), []);
  const [typeFilter, setTypeFilter] = useState(null);

  return (
    <Section
      title="Partners"
      note="Who CISUC's projects are run with — companies and institutions named in the site's Partners field, not funders."
    >
      <AsyncBoundary state={state}>
        {({ partners, by_type: byType, coverage: cov, caveat }) => {
          const rows = typeFilter ? partners.filter((p) => p.partner_type === typeFilter) : partners;

          return (
            <>
              <div className="tiles">
                <Tile
                  value={`${count(cov.projects_with_parsed_partners)} / ${count(cov.detail_fetched_ok)}`}
                  label="Projects with a parsed partner"
                  note="The rest published no Partners field at all"
                />
                <Tile value={count(cov.distinct_partners)} label="Distinct partners" />
                {byType.map((t) => (
                  <Tile
                    key={t.partner_type}
                    value={count(t.distinct_partners)}
                    label={`${TYPE_LABEL[t.partner_type] || t.partner_type} partners`}
                    note={`${count(t.project_count)} projects`}
                  />
                ))}
              </div>

              <div className="group-pills">
                <button
                  type="button"
                  className="group-pill"
                  aria-pressed={typeFilter === null}
                  onClick={() => setTypeFilter(null)}
                >
                  All partners
                </button>
                {TYPES.map((t) => (
                  <button
                    key={t}
                    type="button"
                    className="group-pill"
                    aria-pressed={typeFilter === t}
                    onClick={() => setTypeFilter(typeFilter === t ? null : t)}
                  >
                    <span className="swatch" style={{ background: partnerTypeColorVar(t) }} />
                    {TYPE_LABEL[t]}
                  </button>
                ))}
              </div>

              <ChartWithTable
                title="Top partners by number of projects"
                note="Top 20 partners by project count; the long tail is collapsed into “Other academic” / “Other industry”. Source: sql/partners_breakdown.sql"
                columns={[
                  { key: 'partner_name', label: 'Partner' },
                  {
                    key: 'partner_type',
                    label: 'Type',
                    render: (r) => TYPE_LABEL[r.partner_type] || r.partner_type,
                  },
                  {
                    key: 'project_count',
                    label: 'Projects',
                    numeric: true,
                    render: (r) => count(r.project_count),
                  },
                ]}
                rows={rows}
                getKey={(r) => r.partner_name}
              >
                <CategoryBars
                  data={rows.map((r) => ({ ...r, partner_short: truncate(r.partner_name, 34) }))}
                  categoryKey="partner_short"
                  valueKey="project_count"
                  slotOf={(r) => partnerTypeSlot(r.partner_type)}
                  valueFormat={count}
                  seriesLabel="Projects"
                  categoryWidth={220}
                />
              </ChartWithTable>

              <Caveat>{caveat}</Caveat>
            </>
          );
        }}
      </AsyncBoundary>
    </Section>
  );
}
