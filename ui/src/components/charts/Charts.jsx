/* Small, purpose-built SVG/HTML charts. A charting library would be several
   times the size of this whole bundle for a handful of shapes, none of which
   need pan, zoom, or a legend engine. All of them inherit theme colours from
   CSS custom properties, so light and dark are the same component.

   Mark conventions, shared by every chart here: bars/columns at most 24px
   thick with a 4px rounded data-end and a square baseline; a 2px surface gap
   between touching fills; hairline, solid gridlines; values and labels in
   text tokens, never in the series colour. */

import { useId, useMemo, useState } from "react";
import { pct } from "../../lib/format.js";

/* ------------------------------------------------------------ ring ------ */

/** A single ratio against a whole. The track is a lighter step of the same
    ramp as the fill, so the state reads across the entire circle. */
export function Donut({ value, size = 62, stroke = 8, color = "var(--accent)", track, label }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div className="donut" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label}>
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={track ?? "var(--accent-soft-2)"} strokeWidth={stroke}
        />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${(clamped / 100) * c} ${c}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dasharray 700ms var(--ease)" }}
        />
      </svg>
      <span className="donut__value" style={{ fontSize: size > 70 ? "1rem" : size > 56 ? "0.8125rem" : "0.6875rem" }}>
        {Math.round(clamped)}%
      </span>
    </div>
  );
}

/* --------------------------------------------------------- stacked bar --- */

/** One horizontal 100% bar: how tissue area splits across classes. Outer
    ends rounded by the track, interior joins square, 2px surface gaps. */
export function StackBar({ segments, height = 12, gap = 2 }) {
  const total = segments.reduce((sum, s) => sum + s.value, 0) || 1;
  const visible = segments.filter((s) => s.value > 0);
  return (
    <div
      className="stackbar"
      style={{ gap, height }}
      role="img"
      aria-label={segments.map((s) => `${s.label} ${pct(s.value)}`).join(", ")}
    >
      {visible.map((s) => (
        <div
          key={s.label}
          className="stackbar__seg"
          title={`${s.label} — ${pct(s.value)}`}
          style={{ flexGrow: s.value / total, background: s.color }}
        />
      ))}
    </div>
  );
}

/* --------------------------------------------------------- grouped bars --- */

/** Model vs. baseline, one pair per intensity class. */
export function CompareBars({ rows, modelLabel = "Model", baselineLabel = "Baseline" }) {
  const max = Math.max(1, ...rows.flatMap((r) => [r.model, r.baseline]));
  return (
    <div className="compare-bars">
      {rows.map((row) => (
        <div key={row.label} className="compare-bars__row">
          <div className="compare-bars__head">
            <span>
              <span className="swatch" style={{ background: row.color }} />
              {row.label}
            </span>
            <span className="num">
              <b>{pct(row.model, 2)}</b> <span className="muted">vs {pct(row.baseline, 2)}</span>
            </span>
          </div>
          <HBar width={(row.model / max) * 100} color={row.color} title={`${modelLabel} ${pct(row.model, 2)}`} />
          <HBar
            width={(row.baseline / max) * 100}
            color="var(--text-3)"
            thin
            title={`${baselineLabel} ${pct(row.baseline, 2)}`}
          />
        </div>
      ))}
    </div>
  );
}

function HBar({ width, color, thin = false, title }) {
  return (
    <div className={`hbar${thin ? " hbar--thin" : ""}`} title={title}>
      <div className="hbar__fill" style={{ width: `${Math.max(0.8, width)}%`, background: color }} />
    </div>
  );
}

/* ------------------------------------------------------- class bars ------ */

/** An ordered distribution (0 / 1+ / 2+ / 3+ / cannot assess): one bar per
    bucket in its class colour, count at the tip, label beside the mark. */
export function ClassBars({ rows }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  const total = rows.reduce((s, r) => s + r.count, 0);
  return (
    <div className="class-bars" role="list">
      {rows.map((r) => (
        <div key={r.key} className="class-bars__row" role="listitem" title={`${r.label}: ${r.count}`}>
          <span className="class-bars__label">
            <span className="swatch" style={{ background: r.color }} />
            {r.label}
          </span>
          <span className="class-bars__track">
            <span
              className="class-bars__fill"
              style={{ width: `${(r.count / max) * 100}%`, background: r.color }}
            />
          </span>
          <span className="class-bars__value num">
            {r.count}
            <small>{total ? ` · ${Math.round((r.count / total) * 100)}%` : ""}</small>
          </span>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- columns --- */

/** One series over days. The latest day is the emphasised mark (accent);
    the rest sit in the de-emphasis step. Each column is its own hover and
    focus target; the peak and the latest value are labelled directly. */
export function ColumnChart({ data, height = 150, formatDay, emptyLabel }) {
  const [hover, setHover] = useState(null);
  const max = Math.max(1, ...data.map((d) => d.count));
  const top = niceTop(max);
  const peak = data.reduce((best, d, i) => (d.count > data[best].count ? i : best), 0);
  const last = data.length - 1;
  const total = data.reduce((s, d) => s + d.count, 0);

  return (
    <div className="columns">
      <div className="columns__plot" style={{ height }} onMouseLeave={() => setHover(null)}>
        <div className="columns__grid" aria-hidden="true">
          <span data-v={top} />
          <span data-v={top / 2} />
          <span data-v={0} />
        </div>
        <div className="columns__bars">
          {data.map((d, i) => {
            const h = (d.count / top) * 100;
            const labelled = d.count > 0 && (i === peak || i === last);
            return (
              <button
                key={i}
                type="button"
                className={`columns__slot${hover === i ? " is-hover" : ""}`}
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
                aria-label={`${formatDay(d.day)}: ${d.count}`}
              >
                {hover === i ? (
                  <span className="columns__tip" style={{ bottom: `calc(${h}% + 10px)` }}>
                    <b>{d.count}</b>
                    <span>{formatDay(d.day)}</span>
                  </span>
                ) : labelled ? (
                  <span className="columns__label" style={{ bottom: `calc(${h}% + 4px)` }}>
                    {d.count}
                  </span>
                ) : null}
                <span
                  className={`columns__bar${i === last ? " is-current" : ""}`}
                  style={{ height: d.count ? `${h}%` : 0 }}
                />
              </button>
            );
          })}
        </div>
      </div>
      <div className="columns__axis" aria-hidden="true">
        {data.map((d, i) => (
          <span key={i}>{i % 2 === (last % 2) ? d.day.getDate() : ""}</span>
        ))}
      </div>
      {total === 0 && emptyLabel ? <p className="columns__empty">{emptyLabel}</p> : null}
    </div>
  );
}

/* The axis top, chosen so the midline tick is a whole number of reviews
   too: a gridline labelled "3" that actually sits at 2.5 is a wrong axis. */
function niceTop(n) {
  if (n <= 10) return Math.max(2, n % 2 ? n + 1 : n);
  const mag = 10 ** Math.floor(Math.log10(n));
  for (const step of [1, 1.2, 1.6, 2, 3, 4, 5, 6, 8, 10]) {
    if (step * mag >= n) return step * mag;
  }
  return 10 * mag;
}

/* ------------------------------------------------------------ sparkline --- */

/** A 14-point trend for a stat tile: de-emphasis line and wash, with the
    current point in the accent and ringed in the surface colour. */
export function Sparkline({ values, width = 132, height = 40, color = "var(--accent)" }) {
  const gradientId = useId();
  const { line, area, end } = useMemo(() => {
    const max = Math.max(1, ...values);
    const points = values.map((v, i) => {
      const x = 4 + (i / (values.length - 1 || 1)) * (width - 8);
      const y = height - 5 - (v / max) * (height - 12);
      return [x, y];
    });
    const d = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
    const [lx] = points[points.length - 1] ?? [0];
    return { line: d, area: `${d} L${lx} ${height} L4 ${height} Z`, end: points[points.length - 1] };
  }, [values, width, height]);

  if (!values.length) return null;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" className="sparkline">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.16" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path d={line} fill="none" stroke={color} strokeOpacity="0.55" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {end ? <circle cx={end[0]} cy={end[1]} r="4" fill={color} stroke="var(--surface)" strokeWidth="2" /> : null}
    </svg>
  );
}

/* ----------------------------------------------------------- heat legend --- */

/** The DAB heatmap's colour bar, drawn from the server's own stops so the
    bar and the pixels cannot drift. Ticks mark the three class thresholds;
    below the first one the heat fades out, which the bar shows too. */
export function HeatLegend({ legend, title, lowLabel }) {
  if (!legend?.stops?.length) return null;
  const stops = legend.stops.map((s) => `${s.color} ${(s.at * 100).toFixed(1)}%`).join(", ");
  const fade = (legend.fade_below ?? 0) * 100;
  return (
    <div className="heat-legend">
      <div className="heat-legend__title">{title}</div>
      <div className="heat-legend__bar" style={{ "--heat": `linear-gradient(90deg, ${stops})`, "--fade": `${fade}%` }}>
        {legend.ticks.map((tick) => (
          <span key={tick.label} className="heat-legend__tick" style={{ left: `${tick.at * 100}%` }} />
        ))}
      </div>
      <div className="heat-legend__labels">
        <span style={{ left: 0 }}>{lowLabel}</span>
        {legend.ticks.map((tick) => (
          <span key={tick.label} style={{ left: `${tick.at * 100}%` }}>
            {tick.label}
          </span>
        ))}
      </div>
    </div>
  );
}
