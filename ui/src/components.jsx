// Shared pieces every view is built from: async state, stat tiles, caveats,
// tables, and the two chart wrappers (categorical bars, magnitude-over-time
// lines) that carry the `dataviz` mark specs so no individual view re-derives
// them.

import { useEffect, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { fillClass, slotVar } from './colors';

/** Fetch-on-mount with the three states every view needs to render. */
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ loading: true, error: null, data: null });
  useEffect(() => {
    let live = true;
    setState({ loading: true, error: null, data: null });
    fn()
      .then((data) => live && setState({ loading: false, error: null, data }))
      .catch((error) => live && setState({ loading: false, error, data: null }));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export function AsyncBoundary({ state, children }) {
  if (state.loading) return <p className="state">Loading…</p>;
  if (state.error) return <p className="state error">{state.error.message}</p>;
  if (!state.data) return null;
  return children(state.data);
}

/** External-link marker. An inline SVG rather than the "↗" character, which
 *  renders as a tofu box wherever the font lacks U+2197 — the headless
 *  Chromium used to screenshot this app is one such place, and a user on a
 *  minimal Linux desktop is another. */
export function ExternalLink({ href, children, title }) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" title={title} className="ext-link">
      {children}
      <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
        <path
          d="M6 3h7v7M13 3 7 9M11 10.5V13H3V5h2.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </a>
  );
}

export function Section({ title, note, children }) {
  return (
    <section className="section">
      <h2>{title}</h2>
      {note ? <p className="section-note">{note}</p> : null}
      {children}
    </section>
  );
}

export function Caveat({ label = 'How to read this', children }) {
  return (
    <p className="caveat">
      <strong>{label}:</strong> {children}
    </p>
  );
}

export function Tile({ value, label, note }) {
  return (
    <div className="tile">
      <div className="tile-value">{value}</div>
      <div className="tile-label">{label}</div>
      {note ? <div className="tile-note">{note}</div> : null}
    </div>
  );
}

/** A data table. Present on every chart view — it is both the accessibility
 *  fallback and the relief the palette's light-mode contrast WARN requires. */
export function DataTable({ columns, rows, getKey }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} className={col.numeric ? 'num' : undefined} scope="col">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={getKey ? getKey(row, i) : i}>
              {columns.map((col) => (
                <td key={col.key} className={col.numeric ? 'num' : undefined}>
                  {col.render ? col.render(row) : row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Chart + its table view, toggled. The table is never removed from the DOM
 *  tree on a whim — it is the documented fallback for colour-only encoding. */
export function ChartWithTable({ title, note, children, columns, rows, getKey }) {
  const [showTable, setShowTable] = useState(false);
  return (
    <div className="card">
      <p className="chart-title">{title}</p>
      {note ? <p className="chart-note">{note}</p> : null}
      <button
        type="button"
        className="table-toggle"
        aria-expanded={showTable}
        onClick={() => setShowTable((v) => !v)}
      >
        {showTable ? 'Show chart' : 'Show table'}
      </button>
      {showTable ? (
        <DataTable columns={columns} rows={rows} getKey={getKey} />
      ) : (
        children
      )}
    </div>
  );
}

function TooltipBox({ active, payload, label, formatter, seriesLabel }) {
  if (!active || !payload || !payload.length) return null;
  const entry = payload[0];
  const swatch = slotVar(entry.payload.__slot || 'sequential');
  return (
    <div className="tooltip">
      <div className="tooltip-label">{label}</div>
      <div className="tooltip-row">
        <span className="swatch" style={{ background: swatch }} />
        <span>
          {seriesLabel}: {formatter ? formatter(entry.value) : entry.value}
        </span>
      </div>
    </div>
  );
}

// Ticks are styled by .viz-tick in theme.css, for the same
// attribute-vs-property reason as every other mark — see colors.js.
const AXIS_TICK = { className: 'viz-tick' };

/**
 * Horizontal categorical bars — the default for "magnitude per named thing"
 * where the names are long enough that vertical bars would need rotated
 * labels. One value per category, so no legend (the title names the series);
 * every bar is directly labelled, which is also the relief the light-mode
 * contrast WARN requires.
 */
export function CategoryBars({
  data,
  categoryKey,
  valueKey,
  slotOf,
  valueFormat,
  seriesLabel,
  height,
  categoryWidth = 150,
  labelWidth = 72,
}) {
  const rows = data.map((d) => ({ ...d, __slot: slotOf(d) }));
  return (
    <ResponsiveContainer width="100%" height={height || Math.max(160, rows.length * 26 + 40)}>
      <BarChart
        data={rows}
        layout="vertical"
        // The right margin is the direct labels' room. Too small and they are
        // clipped by the plot area rather than wrapped or dropped.
        margin={{ top: 4, right: labelWidth, bottom: 4, left: 4 }}
      >
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tick={AXIS_TICK} tickFormatter={valueFormat} />
        <YAxis type="category" dataKey={categoryKey} tick={AXIS_TICK} width={categoryWidth} />
        <Tooltip
          cursor={{ className: 'viz-cursor' }}
          content={<TooltipBox formatter={valueFormat} seriesLabel={seriesLabel} />}
        />
        <Bar
          dataKey={valueKey}
          // 4px rounded data-end, square against the baseline.
          radius={[0, 4, 4, 0]}
          barSize={14}
          isAnimationActive={false}
        >
          {rows.map((row, i) => (
            <Cell
              key={`${row[categoryKey]}-${i}`}
              className={`viz-bar-cell ${fillClass(row.__slot)}`}
            />
          ))}
          {/* Direct labels on every bar. Not decoration: three of the six
              categorical slots sit below 3:1 against the light surface, and
              the dataviz relief rule requires visible labels or a table view
              wherever they are used — this ships both. An explicit LabelList,
              not Bar's `label` shorthand, which drops the formatter here. */}
          <LabelList
            dataKey={valueKey}
            position="right"
            className="viz-label"
            formatter={valueFormat}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function StackedTooltipBox({ active, payload, label, segmentKeys, slotOf, seriesLabelOf, valueFormat }) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0].payload;
  const present = segmentKeys.filter((key) => row[key]);
  return (
    <div className="tooltip">
      <div className="tooltip-label">{label}</div>
      {present.map((key) => (
        <div className="tooltip-row" key={key}>
          <span className="swatch" style={{ background: slotVar(slotOf(key)) }} />
          <span>
            {seriesLabelOf(key)}: {valueFormat ? valueFormat(row[key]) : row[key]}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * Stacked categorical bars — CategoryBars' layout, but each bar splits into
 * segments that carry an entity's own identity (e.g. research group) rather
 * than encoding a second magnitude. One `<Bar>` per segment key, sharing a
 * `stackId` so they lay end to end; every segment gets its colour from a
 * `<Cell>` (not the `<Bar>` itself) for the same attribute-vs-property
 * reason documented in colors.js — a class resolves the CSS var, a fill
 * attribute does not.
 */
export function StackedCategoryBars({
  data,
  categoryKey,
  segmentKeys,
  slotOf,
  valueFormat,
  seriesLabelOf,
  height,
  categoryWidth = 150,
}) {
  const lastKey = segmentKeys[segmentKeys.length - 1];
  return (
    <ResponsiveContainer width="100%" height={height || Math.max(160, data.length * 26 + 40)}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 16, bottom: 4, left: 4 }}
      >
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tick={AXIS_TICK} tickFormatter={valueFormat} />
        <YAxis type="category" dataKey={categoryKey} tick={AXIS_TICK} width={categoryWidth} />
        <Tooltip
          cursor={{ className: 'viz-cursor' }}
          content={
            <StackedTooltipBox
              segmentKeys={segmentKeys}
              slotOf={slotOf}
              seriesLabelOf={seriesLabelOf}
              valueFormat={valueFormat}
            />
          }
        />
        {segmentKeys.map((key) => (
          <Bar
            key={key}
            dataKey={key}
            stackId="stack"
            // Only the outer edge of the whole stack is rounded, square
            // where segments meet.
            radius={key === lastKey ? [0, 4, 4, 0] : 0}
            isAnimationActive={false}
          >
            {data.map((row, i) => (
              <Cell
                key={`${row[categoryKey]}-${key}-${i}`}
                className={`viz-bar-cell ${fillClass(slotOf(key))}`}
              />
            ))}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/**
 * Change over time — one line, 2px, markers only when the series is short
 * enough that they do not collide. Crosshair + tooltip by default.
 */
export function TimeLine({ data, categoryKey, valueKey, valueFormat, seriesLabel, height = 220 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey={categoryKey} tick={AXIS_TICK} minTickGap={16} />
        <YAxis tick={AXIS_TICK} tickFormatter={valueFormat} width={70} />
        <Tooltip
          cursor={{ className: 'viz-crosshair', strokeWidth: 1 }}
          content={<TooltipBox formatter={valueFormat} seriesLabel={seriesLabel} />}
        />
        <Line
          type="monotone"
          dataKey={valueKey}
          className="viz-line"
          strokeWidth={2}
          isAnimationActive={false}
          // Markers only while they cannot collide; past that the line alone
          // carries the shape and dots become noise.
          dot={data.length <= 24 ? { className: 'viz-dot', r: 3, strokeWidth: 0 } : false}
          activeDot={{ className: 'viz-active-dot', r: 5, strokeWidth: 2 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Identity legend for the six research groups. Always present where colour
 *  carries identity across more than one chart.
 *
 *  Pass `selected` (a Set of codes) and `onToggle` to make it double as a
 *  click-to-filter control: each entry becomes a toggle button, an empty
 *  `selected` means "show everything" (never an empty chart), and the
 *  currently-selected entries stay full-strength while the rest dim. */
export function GroupLegend({ groups, colorOf, selected, onToggle }) {
  const interactive = typeof onToggle === 'function';
  const filtering = interactive && selected && selected.size > 0;
  return (
    <div className={`legend${filtering ? ' legend-filtering' : ''}`}>
      {groups.map((g) =>
        interactive ? (
          <button
            type="button"
            key={g.code}
            className="legend-item legend-item-button"
            aria-pressed={selected.has(g.code)}
            onClick={() => onToggle(g.code)}
          >
            <span className="swatch" style={{ background: colorOf(g) }} />
            {g.code} — {g.name}
          </button>
        ) : (
          <span className="legend-item" key={g.code}>
            <span className="swatch" style={{ background: colorOf(g) }} />
            {g.code} — {g.name}
          </span>
        ),
      )}
    </div>
  );
}
