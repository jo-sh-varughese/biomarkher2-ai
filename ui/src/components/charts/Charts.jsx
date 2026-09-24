/* Small, purpose-built SVG charts. A charting library would be several times
   the size of this whole bundle for four shapes, none of which need pan,
   zoom, or a legend engine. All of them scale with viewBox and inherit theme
   colours from CSS custom properties. */

import { useId, useMemo, useState } from "react";
import { pct } from "../../lib/format.js";

/* ------------------------------------------------------------ donut ------ */

export function Donut({ value, size = 62, stroke = 8, color = "var(--accent)", label }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div style={{ position: "relative", width: size, height: size, flex: "none" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label}>
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke="var(--line)" strokeWidth={stroke}
        />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${(clamped / 100) * c} ${c}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dasharray 700ms cubic-bezier(.32,.72,0,1)" }}
        />
      </svg>
      <div
        style={{
          position: "absolute", inset: 0,
          display: "grid", placeItems: "center",
          fontSize: size > 56 ? "0.8125rem" : "0.6875rem",
          fontWeight: 800, letterSpacing: "-0.03em",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {Math.round(clamped)}%
      </div>
    </div>
  );
}

/* --------------------------------------------------------- stacked bar --- */

/** A single horizontal bar showing how tissue area splits across classes. */
export function StackBar({ segments, height = 12, gap = 2 }) {
  const total = segments.reduce((sum, s) => sum + s.value, 0) || 1;
  return (
    <div
      style={{ display: "flex", gap, height, borderRadius: 99, overflow: "hidden" }}
      role="img"
      aria-label={segments.map((s) => `${s.label} ${pct(s.value)}`).join(", ")}
    >
      {segments.map((s) => (
        <div
          key={s.label}
          title={`${s.label} — ${pct(s.value)}`}
          style={{
            width: `${(s.value / total) * 100}%`,
            background: s.color,
            borderRadius: 99,
            transition: "width 700ms cubic-bezier(.32,.72,0,1)",
          }}
        />
      ))}
    </div>
  );
}

/* --------------------------------------------------------- grouped bars --- */

/** Model vs. baseline, one pair per intensity class. */
export function CompareBars({ rows }) {
  const max = Math.max(1, ...rows.flatMap((r) => [r.model, r.baseline]));
  return (
    <div style={{ display: "grid", gap: 16 }}>
      {rows.map((row) => (
        <div key={row.label} style={{ display: "grid", gap: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem" }}>
            <span style={{ fontWeight: 600 }}>
              <span className="swatch" style={{ background: row.color }} />
              {row.label}
            </span>
            <span className="num muted">
              {pct(row.model, 2)} <span style={{ opacity: 0.45 }}>vs {pct(row.baseline, 2)}</span>
            </span>
          </div>
          <div style={{ display: "grid", gap: 3 }}>
            <Bar width={(row.model / max) * 100} color={row.color} title={`Model ${pct(row.model, 2)}`} />
            <Bar
              width={(row.baseline / max) * 100}
              color="var(--line-strong)"
              height={5}
              title={`Baseline ${pct(row.baseline, 2)}`}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function Bar({ width, color, height = 9, title }) {
  return (
    <div
      style={{ height, borderRadius: 99, background: "var(--surface-sunken)", overflow: "hidden" }}
      title={title}
    >
      <div
        style={{
          width: `${Math.max(1.5, width)}%`,
          height: "100%",
          background: color,
          borderRadius: 99,
          transition: "width 700ms cubic-bezier(.32,.72,0,1)",
        }}
      />
    </div>
  );
}

/* ------------------------------------------------------------- columns --- */

/** Reviews per day. Hovering a column reveals its value above the axis. */
export function ColumnChart({ data, height = 132, color = "var(--accent)" }) {
  const [hover, setHover] = useState(null);
  const max = Math.max(1, ...data.map((d) => d.count));

  return (
    <div>
      <div
        style={{
          display: "flex", alignItems: "flex-end", gap: 6,
          height, padding: "18px 0 0",
        }}
        onMouseLeave={() => setHover(null)}
      >
        {data.map((d, i) => {
          const active = hover === i;
          return (
            <div
              key={i}
              onMouseEnter={() => setHover(i)}
              style={{ flex: 1, position: "relative", height: "100%", display: "flex", alignItems: "flex-end" }}
            >
              {active ? (
                <span
                  style={{
                    position: "absolute", bottom: "100%", left: "50%",
                    transform: "translate(-50%, -6px)",
                    padding: "2px 7px", borderRadius: 6,
                    background: "var(--surface-inverse)", color: "var(--text-inverse)",
                    fontSize: "0.625rem", fontWeight: 700, whiteSpace: "nowrap",
                  }}
                >
                  {d.count}
                </span>
              ) : null}
              <div
                style={{
                  width: "100%",
                  height: `${Math.max(6, (d.count / max) * 100)}%`,
                  borderRadius: 6,
                  background: active ? color : "var(--accent-soft-2)",
                  transition: "background 130ms, height 700ms cubic-bezier(.32,.72,0,1)",
                }}
              />
            </div>
          );
        })}
      </div>
      <div
        style={{
          display: "flex", gap: 6, marginTop: 8,
          fontSize: "0.625rem", color: "var(--text-3)",
        }}
      >
        {data.map((d, i) => (
          <span key={i} style={{ flex: 1, textAlign: "center" }}>
            {i % 3 === 0 ? d.day.getDate() : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ sparkline --- */

export function Sparkline({ values, width = 132, height = 40, color = "var(--accent)" }) {
  const gradientId = useId();
  const { line, area } = useMemo(() => {
    const max = Math.max(...values);
    const min = Math.min(...values);
    const span = max - min || 1;
    const points = values.map((v, i) => {
      const x = (i / (values.length - 1 || 1)) * width;
      const y = height - 3 - ((v - min) / span) * (height - 8);
      return [x, y];
    });
    const d = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
    return { line: d, area: `${d} L${width} ${height} L0 ${height} Z` };
  }, [values, width, height]);

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
