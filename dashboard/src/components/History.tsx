import type { CiReport, HealthPoint } from "../types";
import { bandVar } from "../lib/score";

/*
 * Health over time. A score is a fact; a trajectory is the thing a maintainer actually asks
 * about -- "did this change help?" -- and it is the reason `ci --history` exists. The six score
 * bands sit faintly behind the line so a reader sees not just the shape but which band the
 * server is in, the same bands the badge colours by. Lint and selection are drawn lighter
 * beneath the composite, and the selection line simply does not start until the first run that
 * measured it, because a lint-only point has no selection to plot.
 */

const W = 760;
const H = 300;
const PAD = { top: 24, right: 20, bottom: 40, left: 36 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;

// Band floors, high to low, mirroring health.py. Drawn as faint horizontal regions.
const BANDS: Array<[number, number, string]> = [
  [90, 100, "var(--band-brightgreen)"],
  [75, 90, "var(--band-green)"],
  [60, 75, "var(--band-yellowgreen)"],
  [45, 60, "var(--band-yellow)"],
  [30, 45, "var(--band-orange)"],
  [0, 30, "var(--band-red)"],
];

function y(v: number): number {
  return PAD.top + (1 - v / 100) * INNER_H;
}
function x(i: number, n: number): number {
  if (n <= 1) return PAD.left + INNER_W / 2;
  return PAD.left + (i / (n - 1)) * INNER_W;
}

function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function line(values: Array<number | null>, n: number): string {
  // A gap-tolerant polyline: a run of consecutive present values becomes one path segment,
  // so the selection line does not draw a phantom leg across the lint-only prefix.
  let d = "";
  let pen = false;
  values.forEach((v, i) => {
    if (v == null) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${x(i, n).toFixed(1)} ${y(v).toFixed(1)} `;
    pen = true;
  });
  return d.trim();
}

export function History({ report }: { report: CiReport }) {
  const points = report.history ?? [];

  if (points.length === 0) {
    return (
      <div className="empty card">
        <p className="empty-title">No history yet.</p>
        <p className="muted">
          Pass <code className="tok">--history history.json</code> to{" "}
          <code className="tok">mcp-toolgauge ci</code> and every run appends a point. Commit the
          file, publish it, and this chart draws your score over time.
        </p>
      </div>
    );
  }

  const n = points.length;
  const overall = points.map((p) => p.health.overall);
  const lint = points.map((p) => p.health.lint_score);
  const evals = points.map((p) => p.health.eval_score ?? null);
  const last = points[n - 1] as HealthPoint;

  return (
    <div>
      <div className="section-label">
        <h2>
          {n} scored runs <span className="rest">since the first commit</span>
        </h2>
      </div>

      <div className="card chart-card">
        <svg
          className="chart"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="Health score over time"
        >
          {BANDS.map(([lo, hi, color]) => (
            <rect
              key={lo}
              x={PAD.left}
              y={y(hi)}
              width={INNER_W}
              height={y(lo) - y(hi)}
              fill={color}
              opacity={0.07}
            />
          ))}

          {[0, 50, 100].map((v) => (
            <g key={v}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(v)}
                y2={y(v)}
                className="grid"
              />
              <text x={PAD.left - 8} y={y(v) + 4} className="axis-y tnum">
                {v}
              </text>
            </g>
          ))}

          <path d={line(lint, n)} className="series lint" />
          <path d={line(evals, n)} className="series eval" />
          <path d={line(overall, n)} className="series overall" />

          {points.map((p, i) => (
            <g key={i}>
              <circle
                cx={x(i, n)}
                cy={y(p.health.overall)}
                r={4.5}
                fill={bandVar(p.health.overall)}
                stroke="var(--surface)"
                strokeWidth={2}
              />
              <text x={x(i, n)} y={y(p.health.overall) - 12} className="pt-val tnum">
                {p.health.overall}
              </text>
              <text x={x(i, n)} y={H - PAD.bottom + 18} className="axis-x">
                {shortDate(p.recorded_at)}
              </text>
              {p.label && (
                <text x={x(i, n)} y={H - PAD.bottom + 32} className="axis-label mono">
                  {p.label}
                </text>
              )}
            </g>
          ))}
        </svg>

        <div className="chart-legend">
          <span className="legend-item">
            <span className="stroke overall" /> health
          </span>
          <span className="legend-item">
            <span className="stroke lint" /> lint
          </span>
          <span className="legend-item">
            <span className="stroke eval" /> selection
          </span>
        </div>
      </div>

      <p className="history-foot muted">
        Latest: <strong className="tnum">{last.health.overall}</strong> on{" "}
        {shortDate(last.recorded_at)}
        {last.label ? ` (${last.label})` : ""}.
      </p>
    </div>
  );
}
