/** Minimal SVG chart kit — no chart library, theme-aware via CSS variables. */

export interface Point {
  label: string;
  value: number;
}

const PINKS = ["#f9a8d4", "#f472b6", "#ec4899", "#be185d", "#db2777", "#fbcfe8", "#a8124e", "#e0448c"];

function niceMax(values: number[]): number {
  const max = Math.max(...values, 1);
  const magnitude = 10 ** Math.floor(Math.log10(max));
  return Math.ceil(max / magnitude) * magnitude;
}

/** Vertical bars; thin labels, auto-spaced. */
export function BarChart({ points, height = 150, unit = "" }: { points: Point[]; height?: number; unit?: string }) {
  if (!points.length) return <Empty />;
  const width = Math.max(280, points.length * 42);
  const max = niceMax(points.map((p) => p.value));
  const barW = Math.min(30, (width - (points.length + 1) * 8) / points.length);
  const chartH = height - 30;
  return (
    <svg role="img" className="w-full" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <defs>
        <linearGradient id="bar-grad" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0%" stopColor="var(--lumi-accent)" stopOpacity="0.55" />
          <stop offset="100%" stopColor="var(--lumi-accent-2)" />
        </linearGradient>
      </defs>
      {points.map((p, i) => {
        const h = (p.value / max) * chartH;
        const x = 8 + i * ((width - 16) / points.length) + ((width - 16) / points.length - barW) / 2;
        return (
          <g key={p.label}>
            <rect x={x} y={chartH - h} width={barW} height={Math.max(2, h)} rx={Math.min(6, barW / 3)} fill="url(#bar-grad)" />
            {p.value > 0 && (
              <text x={x + barW / 2} y={chartH - h - 4} textAnchor="middle" fontSize="10" className="fill-slate-400">
                {p.value}
                {unit}
              </text>
            )}
            <text x={x + barW / 2} y={height - 8} textAnchor="middle" fontSize="10" className="fill-slate-500">
              {p.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Horizontal bars with left labels and right values. */
export function HBars({ points, unit = "" }: { points: Point[]; unit?: string }) {
  if (!points.length) return <Empty />;
  const max = niceMax(points.map((p) => p.value));
  return (
    <ul className="space-y-2">
      {points.map((p, i) => (
        <li key={p.label} className="flex items-center gap-2 text-xs">
          <span className="w-24 shrink-0 truncate text-slate-300" title={p.label}>
            {p.label}
          </span>
          <span className="flex-1 h-2.5 rounded-full bg-slate-800/70 overflow-hidden" aria-hidden="true">
            <span
              className="block h-full rounded-full"
              style={{
                width: `${Math.max(3, (p.value / max) * 100)}%`,
                background: `linear-gradient(90deg, var(--lumi-accent-2), var(--lumi-accent))`,
                opacity: 0.45 + (0.55 * (points.length - i)) / points.length,
              }}
            />
          </span>
          <span className="w-20 shrink-0 text-right text-slate-500 tabular-nums">
            {p.value}
            {unit}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Donut with a center stat; segments = 2+ {label, value}. */
export function Donut({
  segments,
  centerValue,
  centerLabel,
}: {
  segments: Point[];
  centerValue: string;
  centerLabel: string;
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  const size = 140;
  const stroke = 18;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={centerLabel}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--color-slate-800)" strokeWidth={stroke} />
        {total > 0 &&
          segments.map((s, i) => {
            const fraction = s.value / total;
            const dash = fraction * circumference;
            const el = (
              <circle
                key={s.label}
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={PINKS[i % PINKS.length]}
                strokeWidth={stroke}
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={-offset}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
                strokeLinecap="butt"
              />
            );
            offset += dash;
            return el;
          })}
        <text x="50%" y="47%" textAnchor="middle" fontSize="20" fontWeight="700" className="fill-slate-200">
          {centerValue}
        </text>
        <text x="50%" y="63%" textAnchor="middle" fontSize="10" className="fill-slate-500">
          {centerLabel}
        </text>
      </svg>
      <ul className="space-y-1.5 text-xs">
        {segments.map((s, i) => (
          <li key={s.label} className="flex items-center gap-2 text-slate-300">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: PINKS[i % PINKS.length] }} aria-hidden="true" />
            {s.label}
            <span className="text-slate-500 tabular-nums">{s.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Cumulative line with a soft area fill. */
export function AreaChart({ points, height = 150 }: { points: Point[]; height?: number }) {
  if (points.length < 2) return <Empty />;
  const width = Math.max(280, points.length * 14);
  const max = niceMax(points.map((p) => p.value));
  const stepX = (width - 20) / (points.length - 1);
  const chartH = height - 30;
  const coords = points.map((p, i) => ({
    x: 10 + i * stepX,
    y: chartH - (p.value / max) * chartH,
    p,
  }));
  const line = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  const area = `${line} L${coords[coords.length - 1].x.toFixed(1)},${chartH} L${coords[0].x.toFixed(1)},${chartH} Z`;
  const labelEvery = Math.ceil(points.length / 6);
  return (
    <svg role="img" className="w-full" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <defs>
        <linearGradient id="area-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--lumi-accent-2)" stopOpacity="0.5" />
          <stop offset="100%" stopColor="var(--lumi-accent)" stopOpacity="0.05" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#area-grad)" />
      <path d={line} fill="none" stroke="var(--lumi-accent)" strokeWidth="2" strokeLinejoin="round" />
      {coords.map((c, i) => {
        const isLast = i === coords.length - 1;
        // drop a rhythm label that would collide with the always-shown last one
        const collidesWithLast = isLast || (i % labelEvery === 0 && i + labelEvery > coords.length - 1);
        const show = isLast || (i % labelEvery === 0 && !collidesWithLast);
        return show ? (
          <text key={c.p.label} x={c.x} y={height - 8} textAnchor="middle" fontSize="10" className="fill-slate-500">
            {c.p.label}
          </text>
        ) : null;
      })}
    </svg>
  );
}

function Empty() {
  return <p className="text-xs text-slate-500">暂无数据</p>;
}
