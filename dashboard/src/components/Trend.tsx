import type { CiReport } from "../types";

/*
 * The score, run by run.
 *
 * A score is a fact; a trajectory answers the question a maintainer actually asks, which is
 * "did that change help?". It is why `ci --history` exists, and why the point is appended
 * before the --min-score gate runs -- a failing run still belongs on the chart.
 *
 * Drawn on the same drafting sheet as everything else: a dashed dropline from each point to
 * the date beneath it, the composite in ink, and the two halves it is made of in dashed grey
 * and green under it. The selection line simply does not start until the first run that
 * measured it, because a lint-only point has no selection to plot -- a straight leg across
 * that gap would be an invention.
 */

const W = 900;
const H = 320;
const PAD = { top: 34, right: 26, bottom: 52, left: 34 };
const INNER_W = W - PAD.left - PAD.right;
const INNER_H = H - PAD.top - PAD.bottom;

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

/** A gap-tolerant polyline: each run of present values is its own segment. */
function line(values: ReadonlyArray<number | null>, n: number): string {
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

export function Trend({ report }: { report: CiReport }) {
  const points = report.history ?? [];
  const n = points.length;

  const head = (
    <div className="sec-head">
      <div>
        <span className="n">03</span>
        <h2 className="say">
          The score, <span className="dim">run by run</span>
        </h2>
      </div>
    </div>
  );

  if (n === 0) {
    return (
      <section className="band" id="history">
        {head}
        <div className="nothing">
          <p className="say">
            No history yet. <span className="dim">One run is a number, not a trend.</span>
          </p>
          <p className="how">
            Pass <code className="tok">--history history.json</code> to{" "}
            <code className="tok">mcp-toolgauge ci</code> and every run appends a point, pass or
            fail. Commit the file, publish it, and this chart draws your score over time.
          </p>
        </div>
      </section>
    );
  }

  const first = points[0]!;
  const last = points[n - 1]!;
  const delta = last.health.overall - first.health.overall;

  return (
    <section className="band" id="history">
      {head}

      <div className="wall" style={{ ["--cols" as string]: 3 }}>
        <div className="cell">
          <span className="k">Runs recorded</span>
          <span className="v tnum">{n}</span>
          <span className="s">since {shortDate(first.recorded_at)}</span>
        </div>
        <div className="cell">
          <span className="k">Change</span>
          <span className="v tnum">
            {delta > 0 ? "+" : ""}
            {delta}
          </span>
          <span className="s">
            {first.health.overall} at the first run, {last.health.overall} now
          </span>
        </div>
        <div className="cell">
          <span className="k">Latest</span>
          <span className="v tnum">{last.health.overall}</span>
          <span className="s">
            {shortDate(last.recorded_at)}
            {last.label ? ` · ${last.label}` : ""}
          </span>
        </div>
      </div>

      <div className="chart-wrap">
        <svg
          className="chart"
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label={`Health score over ${n} runs, ${first.health.overall} at the first and ${last.health.overall} at the latest.`}
        >
          {[0, 25, 50, 75, 100].map((v) => (
            <g key={v}>
              <line
                className="grid-line"
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y(v)}
                y2={y(v)}
              />
              <text className="axis" x={PAD.left - 10} y={y(v) + 3.5} textAnchor="end">
                {v}
              </text>
            </g>
          ))}

          {points.map((p, i) => (
            <line
              key={`drop-${i}`}
              className="drop"
              x1={x(i, n)}
              x2={x(i, n)}
              y1={y(p.health.overall)}
              y2={H - PAD.bottom}
            />
          ))}

          <path className="series lint" d={line(points.map((p) => p.health.lint_score), n)} />
          <path
            className="series eval"
            d={line(points.map((p) => p.health.eval_score ?? null), n)}
          />
          <path className="series overall" d={line(points.map((p) => p.health.overall), n)} />

          {points.map((p, i) => (
            <g key={i}>
              <rect
                x={x(i, n) - 4}
                y={y(p.health.overall) - 4}
                width={8}
                height={8}
                fill="var(--surface)"
                stroke="var(--ink)"
                strokeWidth={2}
              />
              <text
                className="val"
                x={x(i, n)}
                y={y(p.health.overall) - 14}
                textAnchor="middle"
              >
                {p.health.overall}
              </text>
              <text
                className="stamp"
                x={x(i, n)}
                y={H - PAD.bottom + 18}
                textAnchor="middle"
              >
                {shortDate(p.recorded_at)}
              </text>
              {p.label && (
                <text
                  className="axis"
                  x={x(i, n)}
                  y={H - PAD.bottom + 33}
                  textAnchor="middle"
                >
                  {p.label}
                </text>
              )}
            </g>
          ))}
        </svg>
      </div>

      <div className="chart-key">
        <span className="item">
          <i className="overall" /> health
        </span>
        <span className="item">
          <i className="lint" /> lint
        </span>
        <span className="item">
          <i className="eval" /> selection
        </span>
      </div>
    </section>
  );
}
