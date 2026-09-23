// The filtered collaboration network — nodes are people, radius ∝ degree
// *within this rendered subgraph* (never the full-graph degree, which would
// no longer match the lines a viewer can count), edges connect collaborators
// at the current floor. `d3-force` is a layout-only dependency: it computes
// x/y once, headless, and this file draws plain SVG from the result — see
// `layout()` below for why a React render per simulation tick is never done.
//
// THE RULE THIS FILE IS BUILT ON: React owns the tree, the DOM owns the
// gesture. Zooming and dragging touch DOM attributes directly through refs
// and commit to React state ONCE, when the gesture ends. Routing per-frame
// interaction through state would re-reconcile every mark on every wheel
// notch — 5,182 elements at floor 1, which the floor picker deliberately
// allows — i.e. exactly the re-render storm `layout()` exists to avoid,
// re-introduced through the mouse instead of the simulation.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3-force';
import { select } from 'd3-selection';
import { zoom, zoomIdentity } from 'd3-zoom';
import { api } from '../api';
// No PersonLink here: the profile link lives on PersonNeighbourhood (Collab.jsx),
// which is now this graph's detail panel too. Clicking a NODE means "focus it",
// and giving that gesture a second meaning would break the interaction — the
// reasoning c6736f2 wrote against the old in-graph panel, unchanged.
import { AsyncBoundary, Caveat, useAsync } from '../components';
import { fillClass, groupSlot, GROUP_ORDER } from '../colors';
import { count } from '../format';

const WIDTH = 800;
const HEIGHT = 600;
const R_MIN = 3;
const R_MAX = 18;

const SCALE_EXTENT = [0.4, 8];
//: Label font size and halo thickness in user units at k=1. BOTH are
//: counter-scaled by 1/k, so text keeps its on-screen size instead of
//: growing into a billboard and the halo does not swallow the glyphs it is
//: meant to separate from the lines behind them.
const LABEL_FONT = 11;
const LABEL_HALO = 3;

//: How many of the highest-degree nodes get a standing label, per zoom band.
//: 91 nodes in 800x600 with unconditional text is unreadable; hover-only
//: does not answer "quero ver o nome das pessoas". So: the hubs always, more
//: as you zoom in, everything once you are close enough to read it.
const ZOOM_BANDS = [
  { until: 1.5, labels: 18 },
  { until: 3, labels: 45 },
  { until: Infinity, labels: Infinity },
];

//: Above this many edges the transparent hit-line layer that carries edge
//: tooltips is not rendered at all. Hit-testing every line is the exact cost
//: `.viz-graph-edge { pointer-events: none }` was added to avoid (theme.css)
//: — floors 2-5 are 1,244 edges or fewer and stay responsive; floor 1's
//: 4,242 do not, and floor 1 exists to be looked at, not probed.
const EDGE_HIT_LIMIT = 1500;

//: Longest tooltip we will build for one edge. The heaviest real edge shares
//: 35 projects, and a 35-title native tooltip is a wall, not a hint.
const TOOLTIP_ITEMS = 8;

//: Project/thesis search results shown at once — a chip row, not a list.
const SEARCH_LIMIT = 12;

function bandFor(k) {
  return ZOOM_BANDS.findIndex((b) => k < b.until);
}

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
 *
 * That source/target rewrite is also why dragging works the way it does:
 * every edge points at the SAME node object the circle was rendered from, so
 * moving a node's x/y moves its incident edges' endpoints by construction.
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

/** slug -> [{ index, end }] for every edge touching that node, so a drag can
 *  rewrite only the lines it actually moves instead of walking all 4,242. */
function incidenceIndex(edges) {
  const map = new Map();
  const add = (slug, index, end) => {
    const list = map.get(slug);
    if (list) list.push({ index, end });
    else map.set(slug, [{ index, end }]);
  };
  edges.forEach((e, i) => {
    add(e.source.slug, i, '1');
    add(e.target.slug, i, '2');
  });
  return map;
}

function edgeTooltip(edge, sharedLabels, nouns) {
  const ids = edge.shared_ids || [];
  const pair = `${edge.source.name} ↔ ${edge.target.name}`;
  const head = `${pair} — ${count(edge.weight)} shared ${edge.weight === 1 ? nouns.one : nouns.many}`;
  if (!ids.length) return head;
  const titles = ids.slice(0, TOOLTIP_ITEMS).map((id) => sharedLabels[id] ?? String(id));
  const more = ids.length > TOOLTIP_ITEMS ? `\n…and ${count(ids.length - TOOLTIP_ITEMS)} more` : '';
  return `${head}:\n• ${titles.join('\n• ')}${more}`;
}

/** Project/thesis search — pure client-side over the graph's own
 *  `shared_labels`. No endpoint and no fetch, deliberately: an item that no
 *  surviving edge references has nothing to highlight, so searching the full
 *  table (the way person search rightly does) would only produce picks that
 *  do nothing. */
function SharedPicker({ sharedLabels, nouns, value, onSelect }) {
  const sharedNoun = nouns.one;
  const [input, setInput] = useState('');
  const entries = useMemo(() => Object.entries(sharedLabels), [sharedLabels]);
  const term = input.trim().toLowerCase();
  const matches = term
    ? entries.filter(([, title]) => title.toLowerCase().includes(term)).slice(0, SEARCH_LIMIT)
    : [];

  return (
    <div className="filters">
      <input
        type="search"
        value={input}
        placeholder={`Highlight a ${sharedNoun} — search a title…`}
        aria-label={`Search a ${sharedNoun} to highlight on the graph`}
        onChange={(e) => setInput(e.target.value)}
      />
      <span className="chips">
        {value != null ? (
          <button type="button" className="link-button" onClick={() => onSelect(null)}>
            ✕ {sharedLabels[value] ?? value}
          </button>
        ) : null}
        {matches.map(([id, title]) => (
          <button
            key={id}
            type="button"
            className="link-button"
            aria-pressed={String(value) === id}
            onClick={() => onSelect(id)}
            title={title}
          >
            {title}
          </button>
        ))}
        {term && !matches.length ? (
          <span className="chart-note">
            No {sharedNoun} matching “{input.trim()}” on any edge at this floor — only the{' '}
            {count(entries.length)} {nouns.many} two collaborators actually share are searchable
            here.
          </span>
        ) : null}
      </span>
    </div>
  );
}

function GraphSvg({ layoutState, focus, onFocus, sharedLabels, nouns, sharedId }) {
  const { nodes, edges, maxDegree } = layoutState;
  const visibleSlugs = useMemo(() => new Set(nodes.map((n) => n.slug)), [nodes]);
  const incident = useMemo(() => incidenceIndex(edges), [edges]);

  const svgRef = useRef(null);
  const zoomLayerRef = useRef(null);
  const labelLayerRef = useRef(null);
  const behaviourRef = useRef(null);
  // The live zoom transform. A ref, not state: every drag needs to read it to
  // convert pointer coordinates, and nothing needs to re-render when it moves.
  const transformRef = useRef(zoomIdentity);
  // Did the gesture that is ending actually move the canvas? Without this a
  // pan ends in a click on the background rect and silently clears the focus.
  const pannedRef = useRef(false);
  const nodeEls = useRef(new Map());
  const labelEls = useRef(new Map());
  const lineEls = useRef([]);
  const hitEls = useRef([]);
  const dragRef = useRef(null);

  // The ONLY thing the zoom pushes into React state, and only when it crosses
  // a threshold: scrolling within one band renders zero times.
  const [band, setBand] = useState(() => bandFor(1));
  const [committed, setCommitted] = useState(0);

  const showHitLines = edges.length <= EDGE_HIT_LIMIT;

  const focusSlug = focus?.slug ?? null;
  // One emphasis concept for two sources. A picked project/thesis lights the
  // edges that carry it; a picked person lights their own neighbourhood.
  const emphasis = useMemo(() => {
    const slugs = new Set();
    const edgeOn = new Set();
    if (sharedId != null) {
      edges.forEach((e, i) => {
        if ((e.shared_ids || []).some((id) => String(id) === String(sharedId))) {
          edgeOn.add(i);
          slugs.add(e.source.slug);
          slugs.add(e.target.slug);
        }
      });
      return { slugs, edgeOn };
    }
    if (!focusSlug || !visibleSlugs.has(focusSlug)) return null;
    slugs.add(focusSlug);
    edges.forEach((e, i) => {
      if (e.source.slug !== focusSlug && e.target.slug !== focusSlug) return;
      edgeOn.add(i);
      slugs.add(e.source.slug);
      slugs.add(e.target.slug);
    });
    return { slugs, edgeOn };
  }, [sharedId, focusSlug, edges, visibleSlugs]);

  // Which nodes carry a standing label: the biggest hubs for this zoom band
  // (`nodes` arrives sorted by descending degree), plus whatever is currently
  // emphasised — a neighbourhood you asked for is always worth naming.
  const labelled = useMemo(() => {
    const top = ZOOM_BANDS[band]?.labels ?? 0;
    const set = new Set(nodes.slice(0, top === Infinity ? nodes.length : top).map((n) => n.slug));
    emphasis?.slugs.forEach((s) => set.add(s));
    return set;
  }, [band, nodes, emphasis]);

  /** clientX/Y -> graph user units. TWO conversions, both required: the SVG
   *  is viewBox="0 0 800 600" at width="100%", so one user unit is not one
   *  screen pixel and the ratio changes with the window (getScreenCTM), and
   *  the zoom transform sits between that and the marks (transform.invert).
   *  Get either wrong and the node slides away from the cursor, worse the
   *  wider the window — which is why this is tested narrow AND wide. */
  const toUser = useCallback((event) => {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM();
    if (!ctm) return null;
    const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse());
    return transformRef.current.invert([p.x, p.y]);
  }, []);

  /** Per-frame drag write: the circle, its label, and ONLY the endpoints of
   *  the lines that actually touch it. Straight to attributes — no setState,
   *  see the file header. */
  const writePosition = useCallback((slug, x, y, radius) => {
    const circle = nodeEls.current.get(slug);
    if (circle) {
      circle.setAttribute('cx', x);
      circle.setAttribute('cy', y);
    }
    const text = labelEls.current.get(slug);
    if (text) {
      text.setAttribute('x', x + radius + 2);
      text.setAttribute('y', y);
    }
    (incident.get(slug) || []).forEach(({ index, end }) => {
      const line = lineEls.current[index];
      if (line) {
        line.setAttribute(`x${end}`, x);
        line.setAttribute(`y${end}`, y);
      }
      const hit = hitEls.current[index];
      if (hit) {
        hit.setAttribute(`x${end}`, x);
        hit.setAttribute(`y${end}`, y);
      }
    });
  }, [incident]);

  /** Writes the current zoom transform to the DOM: one attribute on the zoom
   *  layer, and the two counter-scaled label properties. */
  const applyTransform = useCallback(() => {
    const t = transformRef.current;
    const layer = zoomLayerRef.current;
    if (layer) {
      layer.setAttribute('transform', `translate(${t.x},${t.y}) scale(${t.k})`);
      // Inherited by every stroke rule in the layer (theme.css): line weight
      // carries no data, so it stays a hairline while the geometry scales.
      layer.style.setProperty('--stroke-k', 1 / t.k);
    }
    const labels = labelLayerRef.current;
    if (labels) {
      labels.setAttribute('font-size', LABEL_FONT / t.k);
      labels.setAttribute('stroke-width', LABEL_HALO / t.k);
    }
  }, []);

  // d3-zoom rather than React's onWheel: React registers wheel listeners
  // PASSIVELY, so preventDefault() there is a no-op and the whole page
  // scrolls while you try to zoom. d3 attaches its own non-passive listener.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return undefined;
    const behaviour = zoom()
      .scaleExtent(SCALE_EXTENT)
      // A drag that STARTS on a node moves that node, not the canvas. Filtered
      // here rather than with stopPropagation, because React's synthetic
      // handlers run after d3's native listener has already seen the event.
      .filter((event) => event.type === 'wheel' || !event.target?.closest?.('.viz-graph-node'))
      .on('start', () => {
        pannedRef.current = false;
      })
      .on('zoom', (event) => {
        const t = event.transform;
        transformRef.current = t;
        pannedRef.current = true;
        applyTransform();
        const next = bandFor(t.k);
        setBand((current) => (current === next ? current : next));
      });
    select(svg).call(behaviour).on('dblclick.zoom', null);
    behaviourRef.current = behaviour;
    return () => {
      select(svg).on('.zoom', null);
    };
  }, [layoutState, applyTransform]);

  // After EVERY render, not just zoom events. React owns `font-size` and the
  // layer transform the moment they appear in JSX, so anything that
  // re-renders while zoomed in — a band change, a drag commit, a new focus —
  // would reset the view to k=1 and the labels to billboard size. Keeping
  // them out of the tree and re-asserting them here is what makes "the DOM
  // owns the gesture" hold across renders React did not initiate.
  useEffect(applyTransform);

  const resetView = () => {
    const svg = svgRef.current;
    if (svg && behaviourRef.current) select(svg).call(behaviourRef.current.transform, zoomIdentity);
  };

  const onPointerDown = (event, node) => {
    if (event.button != null && event.button !== 0) return;
    const start = toUser(event);
    if (!start) return;
    event.target.setPointerCapture(event.pointerId);
    dragRef.current = {
      node,
      radius: radiusFor(node.degree, maxDegree),
      dx: node.x - start[0],
      dy: node.y - start[1],
      moved: false,
    };
  };

  const onPointerMove = (event) => {
    const drag = dragRef.current;
    if (!drag) return;
    const at = toUser(event);
    if (!at) return;
    const x = at[0] + drag.dx;
    const y = at[1] + drag.dy;
    // Mutating the laid-out node is the commit: edges hold this very object
    // (see layout()), and React's next render reads x/y from here — so the
    // VDOM never ends up claiming a position the DOM has already left.
    drag.node.x = x;
    drag.node.y = y;
    drag.moved = true;
    writePosition(drag.node.slug, x, y, drag.radius);
  };

  const endDrag = (event) => {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    if (event.target.hasPointerCapture?.(event.pointerId)) {
      event.target.releasePointerCapture(event.pointerId);
    }
    if (!drag.moved) {
      // A press that never moved is a click.
      onFocus(focusSlug === drag.node.slug ? null : { slug: drag.node.slug, name: drag.node.name });
      return;
    }
    // Once per gesture, never per frame: re-render so React's tree matches
    // the DOM the drag has been writing to directly.
    setCommitted((n) => n + 1);
  };

  // Hover names a node whatever the zoom band says — done by toggling a class
  // on the text element itself. Through state it would re-render every mark
  // on every mouseover, for one label.
  const hover = (slug, on) => {
    const text = labelEls.current.get(slug);
    if (text) text.classList.toggle('viz-graph-label-on', on);
  };

  return (
    <div className="graph-layout">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        width="100%"
        height={HEIGHT}
        className="viz-graph"
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        data-committed={committed}
      >
        <rect
          x={0}
          y={0}
          width={WIDTH}
          height={HEIGHT}
          fill="transparent"
          onClick={() => {
            if (!pannedRef.current) onFocus(null);
          }}
        />
        <g ref={zoomLayerRef}>
          <g>
            {edges.map((e, i) => (
              <line
                key={`${e.source.slug}-${e.target.slug}-${i}`}
                ref={(el) => {
                  lineEls.current[i] = el;
                }}
                x1={e.source.x}
                y1={e.source.y}
                x2={e.target.x}
                y2={e.target.y}
                className={
                  'viz-graph-edge' +
                  (emphasis && !emphasis.edgeOn.has(i) ? ' viz-graph-edge-dim' : '') +
                  (emphasis?.edgeOn.has(i) ? ' viz-graph-edge-on' : '')
                }
              />
            ))}
          </g>
          {/* Edge tooltips need a hit target, and .viz-graph-edge is
              pointer-events:none on purpose (theme.css). A separate wide
              transparent layer gives hover a 8-unit-thick line to find
              without making the visible stroke fat — and it is dropped
              entirely above EDGE_HIT_LIMIT rather than slowing floor 1. */}
          {showHitLines ? (
            <g className="viz-graph-hit-layer">
              {edges.map((e, i) => (
                <line
                  key={`hit-${e.source.slug}-${e.target.slug}-${i}`}
                  ref={(el) => {
                    hitEls.current[i] = el;
                  }}
                  x1={e.source.x}
                  y1={e.source.y}
                  x2={e.target.x}
                  y2={e.target.y}
                  className="viz-graph-edge-hit"
                >
                  <title>{edgeTooltip(e, sharedLabels, nouns)}</title>
                </line>
              ))}
            </g>
          ) : null}
          <g>
            {nodes.map((n) => (
              <circle
                key={n.slug}
                ref={(el) => {
                  if (el) nodeEls.current.set(n.slug, el);
                  else nodeEls.current.delete(n.slug);
                }}
                cx={n.x}
                cy={n.y}
                r={radiusFor(n.degree, maxDegree)}
                className={
                  `viz-graph-node ${fillClass(groupSlot(primaryGroup(n.groups)))}` +
                  (emphasis && !emphasis.slugs.has(n.slug) ? ' viz-graph-node-dim' : '') +
                  (focusSlug === n.slug ? ' viz-graph-node-selected' : '')
                }
                onPointerDown={(event) => onPointerDown(event, n)}
                onPointerEnter={() => hover(n.slug, true)}
                onPointerLeave={() => hover(n.slug, false)}
              >
                <title>
                  {`${n.name} — degree ${n.degree} of ${n.degree_full} total`}
                  {n.groups.length ? ` — ${n.groups.join(', ')}` : ''}
                </title>
              </circle>
            ))}
          </g>
          {/* font-size / stroke-width are set imperatively (applyTransform),
              never here: in JSX React would reset them on every render. */}
          <g ref={labelLayerRef} className="viz-graph-labels">
            {nodes.map((n) => (
              <text
                key={n.slug}
                ref={(el) => {
                  if (el) labelEls.current.set(n.slug, el);
                  else labelEls.current.delete(n.slug);
                }}
                x={n.x + radiusFor(n.degree, maxDegree) + 2}
                y={n.y}
                dominantBaseline="central"
                className={`viz-graph-label${labelled.has(n.slug) ? '' : ' viz-graph-label-off'}`}
              >
                {n.name}
              </text>
            ))}
          </g>
        </g>
      </svg>
      <div className="graph-controls">
        <button type="button" onClick={resetView}>
          Reset view
        </button>
        <p className="chart-note">
          Scroll to zoom, drag the background to pan, drag a person to move them. Names appear for
          the busiest people first and for everyone as you zoom in — hover any circle to name it.
        </p>
        {!showHitLines ? (
          <p className="chart-note">
            Edge tooltips are off at this floor — hovering {count(edges.length)} lines costs more
            than it tells you. Raise the floor to read which {nouns.many} an edge stands for.
          </p>
        ) : null}
        {focusSlug && !visibleSlugs.has(focusSlug) ? (
          <p className="chart-note">
            <strong>{focus.name}</strong> is not in this view — they have no collaborator at the
            current floor. Lower it to draw them.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function GraphBody({ data, focus, onFocus }) {
  const [layoutState, setLayoutState] = useState(null);
  const [sharedId, setSharedId] = useState(null);

  useEffect(() => {
    setLayoutState(null);
    setSharedId(null);
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

  // A person and a project are two ways of asking the same question, so only
  // one of them can be the answer on screen: the newer pick wins. Derived
  // rather than synced in an effect — nothing to get out of step.
  const activeShared = focus ? null : sharedId;
  // Singular and plural both come from the API — see collab.SHARED_NOUN.
  const nouns = { one: data.shared_noun, many: data.shared_noun_plural };

  return (
    <div className="card">
      <p className="chart-note">
        {count(data.node_count)} people, {count(data.edge_count)} connections at ≥{data.min_weight}{' '}
        {data.shared_noun === 'project' ? 'shared project(s)' : 'shared thesis/theses'} — node size
        is degree within this view, not the full-graph total.
      </p>
      <SharedPicker
        sharedLabels={data.shared_labels}
        nouns={nouns}
        value={activeShared}
        onSelect={(id) => {
          setSharedId(id);
          if (id != null) onFocus(null);
        }}
      />
      {layoutState ? (
        <GraphSvg
          layoutState={layoutState}
          focus={focus}
          onFocus={onFocus}
          sharedLabels={data.shared_labels}
          nouns={nouns}
          sharedId={activeShared}
        />
      ) : (
        <p className="state">Computing layout…</p>
      )}
      <Caveat label="degree">{data.degree_caveat}</Caveat>
    </div>
  );
}

export default function CollabGraph({ kind, minWeight, focus, onFocus }) {
  const state = useAsync(() => api.collabGraph({ kind, minWeight }), [kind, minWeight]);
  return (
    <AsyncBoundary state={state}>
      {(data) => <GraphBody data={data} focus={focus} onFocus={onFocus} />}
    </AsyncBoundary>
  );
}
