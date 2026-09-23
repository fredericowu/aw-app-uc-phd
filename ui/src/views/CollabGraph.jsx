// The filtered collaboration network — nodes are people, radius ∝ degree
// *within this rendered subgraph* (never the full-graph degree, which would
// no longer match the lines a viewer can count), edges connect collaborators
// at the current floor. `d3-force` is a layout-only dependency: it computes
// x/y once, headless, and this file draws plain SVG from the result — see
// `layout()` below for why a React render per simulation tick is never done.

import { useEffect, useMemo, useState } from 'react';
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3-force';
import { api } from '../api';
import { AsyncBoundary, Caveat, PersonLink, useAsync } from '../components';
import { fillClass, groupSlot, GROUP_ORDER } from '../colors';
import { count } from '../format';
import { GroupChips } from './Collab';

const WIDTH = 800;
const HEIGHT = 600;
const R_MIN = 3;
const R_MAX = 18;

/** A person with several groups gets one fill colour — the first hit in
 *  GROUP_ORDER's own fixed order, not array position — plus the full list
 *  stays visible in the hover title and the side panel. Not a pie-slice
 *  node: colors.js already treats "no validated colour" as worse than grey
 *  for a 7th group, and the same reasoning applies to multi-group nodes. */
function primaryGroup(groups) {
  if (!groups || !groups.length) return null;
  return GROUP_ORDER.find((g) => groups.includes(g)) ?? groups[0];
}

function radiusFor(degree, maxDegree) {
  if (maxDegree <= 0) return R_MIN;
  return R_MIN + (R_MAX - R_MIN) * Math.sqrt(degree / maxDegree);
}

/**
 * Runs the force simulation to convergence off-screen, then hands back
 * laid-out copies once. Never `simulation.on('tick')` -> setState: 300 ticks
 * x hundreds of edges through React's reconciler is the freeze this avoids.
 *
 * `nodes`/`edges` are deep-copied before simulating because d3-force
 * mutates what it is given — it bolts x/y/vx/vy onto every node object and
 * rewrites each edge's `source`/`target` from a slug string into the actual
 * node object reference. Simulating the arrays `useAsync` cached would mean
 * that cached response object silently acquires layout coordinates, and the
 * "same" data would render differently after a re-mount.
 */
function layout(nodes, edges) {
  const maxDegree = nodes.reduce((m, n) => Math.max(m, n.degree), 1);
  const simNodes = nodes.map((n) => ({ ...n }));
  const simEdges = edges.map((e) => ({ ...e }));
  const sim = forceSimulation(simNodes)
    .force('link', forceLink(simEdges).id((d) => d.slug).distance(40).strength(0.2))
    .force('charge', forceManyBody().strength(-80))
    .force('center', forceCenter(WIDTH / 2, HEIGHT / 2))
    .force('collide', forceCollide((d) => radiusFor(d.degree, maxDegree) + 2))
    .stop();
  // sim.tickCount() equivalent: how many ticks it takes alpha to decay below
  // alphaMin, the same formula d3-force's own `simulation()` loop uses
  // internally when it is allowed to run on a timer instead of headless.
  const ticks = Math.ceil(Math.log(sim.alphaMin()) / Math.log(1 - sim.alphaDecay()));
  for (let i = 0; i < ticks; i++) sim.tick();
  return { nodes: simNodes, edges: simEdges, maxDegree };
}

function NeighbourPanel({ slug, kind, visibleSlugs, onClose }) {
  const state = useAsync(() => api.collabPerson(slug, { kind, minWeight: 1, limit: 500 }), [slug, kind]);
  return (
    <div className="card graph-panel">
      <AsyncBoundary state={state}>
        {(person) => (
          <>
            <p className="chart-note">
              {/* The panel HEADER links to the profile; the graph NODE itself
                  deliberately does not. Clicking a node already means "select
                  it and dim the non-incident edges", and giving that gesture a
                  second meaning would break the interaction. */}
              <strong>
                <PersonLink slug={person.person.slug}>{person.person.name}</PersonLink>
              </strong>
              {' — '}
              <GroupChips groups={person.person.groups} />
              {' · '}
              {count(person.total)} collaborator(s) in total (floor removed)
              {' · '}
              <button type="button" className="link-button" onClick={onClose}>
                Close
              </button>
            </p>
            <ul className="graph-panel-list">
              {person.collaborators.map((c) => (
                <li key={c.slug} className={visibleSlugs.has(c.slug) ? '' : 'graph-panel-hidden'}>
                  <PersonLink slug={c.slug}>{c.name}</PersonLink> — weight {count(c.weight)}
                  {!visibleSlugs.has(c.slug) ? ' (hidden by the current floor)' : ''}
                </li>
              ))}
              {!person.collaborators.length ? <li className="chart-note">No collaborators.</li> : null}
            </ul>
          </>
        )}
      </AsyncBoundary>
    </div>
  );
}

function GraphSvg({ layoutState, kind, selectedSlug, onSelect }) {
  const { nodes, edges, maxDegree } = layoutState;
  const visibleSlugs = useMemo(() => new Set(nodes.map((n) => n.slug)), [nodes]);

  // Incident set drives dimming only — positions never change on selection,
  // so a click never re-triggers the layout and the picture never jumps.
  const incident = useMemo(() => {
    if (!selectedSlug) return null;
    const set = new Set([selectedSlug]);
    edges.forEach((e) => {
      if (e.source.slug === selectedSlug) set.add(e.target.slug);
      if (e.target.slug === selectedSlug) set.add(e.source.slug);
    });
    return set;
  }, [selectedSlug, edges]);

  return (
    <div className="graph-layout">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width="100%" height={HEIGHT} className="viz-graph">
        <rect
          x={0}
          y={0}
          width={WIDTH}
          height={HEIGHT}
          fill="transparent"
          onClick={() => onSelect(null)}
        />
        <g>
          {edges.map((e, i) => {
            const dim = incident && !(incident.has(e.source.slug) && incident.has(e.target.slug));
            return (
              <line
                key={`${e.source.slug}-${e.target.slug}-${i}`}
                x1={e.source.x}
                y1={e.source.y}
                x2={e.target.x}
                y2={e.target.y}
                className={`viz-graph-edge${dim ? ' viz-graph-edge-dim' : ''}`}
              />
            );
          })}
        </g>
        <g>
          {nodes.map((n) => {
            const dim = incident && !incident.has(n.slug);
            const slot = groupSlot(primaryGroup(n.groups));
            return (
              <circle
                key={n.slug}
                cx={n.x}
                cy={n.y}
                r={radiusFor(n.degree, maxDegree)}
                className={
                  `viz-graph-node ${fillClass(slot)}` +
                  `${dim ? ' viz-graph-node-dim' : ''}` +
                  `${selectedSlug === n.slug ? ' viz-graph-node-selected' : ''}`
                }
                onClick={() => onSelect(n.slug === selectedSlug ? null : n.slug)}
              >
                <title>
                  {`${n.name} — degree ${n.degree} of ${n.degree_full} total`}
                  {n.groups.length ? ` — ${n.groups.join(', ')}` : ''}
                </title>
              </circle>
            );
          })}
        </g>
      </svg>
      {selectedSlug ? (
        <NeighbourPanel slug={selectedSlug} kind={kind} visibleSlugs={visibleSlugs} onClose={() => onSelect(null)} />
      ) : null}
    </div>
  );
}

function GraphBody({ data, kind }) {
  const [layoutState, setLayoutState] = useState(null);
  const [selectedSlug, setSelectedSlug] = useState(null);

  useEffect(() => {
    setLayoutState(null);
    setSelectedSlug(null);
    let cancelled = false;
    // Floor 1 (~2.5M ops) blocks the main thread for a few hundred ms — yield
    // one frame first so "Computing layout…" actually paints before it does.
    const frame = requestAnimationFrame(() => {
      if (cancelled) return;
      setLayoutState(layout(data.nodes, data.edges));
    });
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
    };
  }, [data]);

  return (
    <div className="card">
      <p className="chart-note">
        {count(data.node_count)} people, {count(data.edge_count)} connections at ≥{data.min_weight}{' '}
        {kind === 'co_project' ? 'shared project(s)' : 'shared thesis/theses'} — node size is degree
        within this view, not the full-graph total.
      </p>
      {layoutState ? (
        <GraphSvg layoutState={layoutState} kind={kind} selectedSlug={selectedSlug} onSelect={setSelectedSlug} />
      ) : (
        <p className="state">Computing layout…</p>
      )}
      <Caveat label="degree">{data.degree_caveat}</Caveat>
    </div>
  );
}

export default function CollabGraph({ kind, minWeight }) {
  const state = useAsync(() => api.collabGraph({ kind, minWeight }), [kind, minWeight]);
  return (
    <AsyncBoundary state={state}>{(data) => <GraphBody data={data} kind={kind} />}</AsyncBoundary>
  );
}
