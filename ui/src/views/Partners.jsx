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
  DataTable,
  ExternalLink,
  Section,
  Tile,
  useAsync,
} from '../components';
import { partnerTypeColorVar, partnerTypeSlot } from '../colors';
import { count, truncate } from '../format';

const TYPE_LABEL = { academic: 'Academic', industry: 'Industry' };
const TYPES = ['academic', 'industry'];

const ROLE_LABEL = { coordinator: 'coordinator', researcher: 'researcher' };
const THESIS_ROLE_LABEL = { author: 'author', supervisor: 'supervisor' };

function PartnerThesisLinks() {
  const state = useAsync(() => api.partnerTheses(), []);
  return (
    <AsyncBoundary state={state}>
      {({ links, coverage: cov, caveat }) => (
        <>
          <div className="tiles">
            <Tile
              value={`${count(cov.partners_with_a_thesis_link)} / ${count(cov.distinct_partners)}`}
              label="Partners reaching a thesis"
              note="Via a shared project and a matched author/supervisor — see the caveat below"
            />
            <Tile
              value={`${count(cov.theses_with_a_partner_link)} / ${count(cov.total_theses)}`}
              label="Theses reaching a partner"
            />
          </div>
          <DataTable
            columns={[
              { key: 'partner_name', label: 'Partner' },
              {
                key: 'partner_type',
                label: 'Type',
                render: (r) => TYPE_LABEL[r.partner_type] || r.partner_type,
              },
              {
                key: 'via',
                label: 'Via',
                render: (r) => (
                  <>
                    {r.project_title} — {ROLE_LABEL[r.via_project_role] || r.via_project_role}{' '}
                    {r.via_person_name}
                  </>
                ),
              },
              {
                key: 'thesis_title',
                label: 'Thesis',
                render: (r) => (
                  <ExternalLink href={r.thesis_source_url}>{r.thesis_title}</ExternalLink>
                ),
              },
              {
                key: 'thesis_role',
                label: 'As',
                render: (r) => THESIS_ROLE_LABEL[r.thesis_role] || r.thesis_role,
              },
              {
                key: 'match_status',
                label: 'Confidence',
                render: (r) => `${r.match_status} (${r.match_confidence})`,
              },
            ]}
            rows={links}
            getKey={(r, i) => `${r.partner_name}-${r.thesis_handle}-${r.via_person_slug}-${i}`}
          />
          <Caveat label="Not a funding relationship">{caveat}</Caveat>
        </>
      )}
    </AsyncBoundary>
  );
}

export default function Partners() {
  const state = useAsync(() => api.partners(), []);
  const [typeFilter, setTypeFilter] = useState(null);

  return (
    <>
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

      <Section
        title="Partners linked to theses"
        note="Closing the “empresas e entidades patrocinadoras” side of the picture — inferred, not observed. Every row shows the project and person the link runs through."
      >
        <PartnerThesisLinks />
      </Section>
    </>
  );
}
