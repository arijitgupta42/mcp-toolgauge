import type { CiReport } from "../types";
import { bandVar, bandWord } from "../lib/score";

/*
 * The top of the report: what the numbers mean, said in a sentence, then the gauge, then the
 * numbers themselves.
 *
 * The sentence comes first deliberately. A maintainer opening this wants the verdict, and a
 * row of tiles makes them assemble it themselves out of four figures. So the page opens with
 * "acme-directory sends 55% of prompts to the tool that should answer them, and lint counts
 * 74 problems across 10 tools" -- and the figures underneath are the evidence for a claim
 * already made, which is a different job from being the claim.
 */

interface Frag {
  t: string;
  dim?: boolean;
}

function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The verdict, as alternating inked and greyed fragments. */
export function verdictFragments(report: CiReport): Frag[] {
  const name = report.server.name ?? "This server";
  const tools = report.lint.tool_count;
  const findings = report.lint.findings?.length ?? 0;
  const evalScore = report.health.eval_score;

  const lint: Frag[] =
    findings === 0
      ? [
          { t: "lint finds ", dim: true },
          { t: "nothing to fix" },
          { t: ` across its ${count(tools, "tool", "tools")}.`, dim: true },
        ]
      : [
          { t: "lint counts ", dim: true },
          { t: count(findings, "problem", "problems") },
          { t: ` across ${count(tools, "tool", "tools")}.`, dim: true },
        ];

  if (evalScore == null) {
    // Lint-only. Saying so in the headline matters: half the score is missing, and a reader
    // who does not notice that will read the composite as harsher than it is.
    return [
      { t: name },
      { t: " was scored on lint alone, and ", dim: true },
      ...lint,
      { t: " Nothing here says whether a model can pick the right one.", dim: true },
    ];
  }

  return [
    { t: name },
    { t: " sends ", dim: true },
    { t: `${evalScore}% of prompts` },
    { t: " to the tool that should answer them, and ", dim: true },
    ...lint,
  ];
}

export function Verdict({ report }: { report: CiReport }) {
  const { health, server, lint } = report;
  const scores = report.eval?.scores;
  const findings = lint.findings?.length ?? 0;
  const errors = health.errors ?? 0;
  const warnings = health.warnings ?? 0;
  const lintOnly = health.eval_score == null;

  return (
    <section className="band">
      <div className="verdict-head">
        <span className="name">{server.name ?? "(unnamed server)"}</span>
        <span className="cap mono">
          {server.version ? `${server.version} · ` : ""}
          {report.target}
        </span>
      </div>

      <h1 className="say verdict-say">
        {verdictFragments(report).map((f, i) =>
          f.dim ? (
            <span className="dim" key={i}>
              {f.t}
            </span>
          ) : (
            <span key={i}>{f.t}</span>
          ),
        )}
      </h1>

      <Gauge score={health.overall} />

      <div className="wall" style={{ ["--cols" as string]: 4 }}>
        <Cell
          k="Lint"
          v={String(health.lint_score)}
          s="half of the health score"
          band={bandVar(health.lint_score)}
        />
        <Cell
          k="Selection"
          v={lintOnly ? "—" : `${health.eval_score}%`}
          s={
            lintOnly
              ? "no eval suite committed"
              : `${scores?.selection_correct ?? 0} of ${scores?.selection_total ?? 0} prompts`
          }
          band={lintOnly ? "var(--grey)" : bandVar(health.eval_score ?? 0)}
        />
        <Cell
          k="Findings"
          v={String(findings)}
          s={
            findings === 0
              ? "a clean lint"
              : `${count(errors, "error", "errors")} · ${count(warnings, "warning", "warnings")}`
          }
        />
        <Cell k="Tools" v={String(lint.tool_count)} s="listed by the server" />
      </div>
    </section>
  );
}

function Cell({
  k,
  v,
  s,
  band,
}: {
  k: string;
  v: string;
  s: string;
  band?: string;
}) {
  return (
    <div
      className={band ? "cell scored" : "cell"}
      style={band ? { ["--band" as string]: band } : undefined}
    >
      <span className="k">{k}</span>
      <span className="v tnum">{v}</span>
      <span className="s">{s}</span>
    </div>
  );
}

/*
 * The health score on a 0-100 rail, with the six bands drawn to their real widths. The point
 * is proportion: 28 is not just "low", it is most of the way down the widest band on the
 * scale, with four bands stacked above it -- which a numeral on its own cannot say.
 *
 * Band floors mirror health.py, the same ladder score.ts ports. Only the band the needle is
 * standing in is drawn at full strength; the rest are ghosted, so the eye lands on the answer.
 */
const SEGMENTS: ReadonlyArray<readonly [number, number, string]> = [
  [0, 30, "var(--band-red)"],
  [30, 45, "var(--band-orange)"],
  [45, 60, "var(--band-yellow)"],
  [60, 75, "var(--band-yellowgreen)"],
  [75, 90, "var(--band-green)"],
  [90, 100, "var(--band-brightgreen)"],
];

const TICKS = [0, 30, 45, 60, 75, 90, 100];

function Gauge({ score }: { score: number }) {
  const at = Math.min(100, Math.max(0, score));
  // The flag would hang off the end of the rail at the extremes, and both are reachable --
  // a server with five errors scores 0, and a clean lint-only server scores 100.
  const flagShift = at < 8 ? "translateX(0)" : at > 92 ? "translateX(-100%)" : "translateX(-50%)";

  return (
    <div className="gauge">
      <div className="gauge-flag" style={{ left: `${at}%`, transform: flagShift }}>
        <span className="v tnum">{at}</span>
        <span className="cap">/100 · {bandWord(at)}</span>
      </div>

      <div className="gauge-bar" aria-hidden="true">
        {SEGMENTS.map(([lo, hi, color]) => (
          <div
            key={lo}
            className="gauge-seg"
            style={{
              flexGrow: hi - lo,
              background: color,
              opacity: at >= lo && (at < hi || hi === 100) ? 1 : 0.17,
            }}
          />
        ))}
      </div>

      <div className="gauge-needle" style={{ left: `${at}%` }} aria-hidden="true" />

      {TICKS.map((t) => (
        <span
          key={t}
          className="gauge-tick"
          style={{
            left: `${t}%`,
            transform: t === 0 ? "translateX(0)" : t === 100 ? "translateX(-100%)" : undefined,
          }}
        >
          {t}
        </span>
      ))}

      <span className="visually-hidden">
        Health {at} out of 100 — {bandWord(at)}.
      </span>
    </div>
  );
}
