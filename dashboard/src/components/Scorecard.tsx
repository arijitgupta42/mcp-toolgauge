import type { CiReport } from "../types";
import { bandVar, bandWord } from "../lib/score";

/*
 * The persistent header: the one health number, and the two halves it is made of. It is the
 * terminal scorecard (`report/ci.py`'s render_ci_table) rendered for a browser -- and it keeps
 * that renderer's cardinal rule, that the composite never appears without lint and selection
 * beside it, because a number that hides what it is made of is a number nobody trusts.
 *
 * A header, deliberately, not a fourth view. The three tabs below it are the report; this is
 * the thing that stays put above all of them.
 */
export function Scorecard({ report }: { report: CiReport }) {
  const { health, server, eval: evaluation } = report;
  const selection = evaluation?.scores;
  const selCorrect = selection?.selection_correct ?? 0;
  const selTotal = selection?.selection_total ?? 0;
  const lintOnly = health.eval_score == null;

  return (
    <section className="scorecard" style={{ ["--band" as string]: bandVar(health.overall) }}>
      <div className="scorecard-hero">
        <div className="score-numeral">
          <span className="numeral display tnum">{health.overall}</span>
          <span className="numeral-max mono">/100</span>
        </div>
        <div className="score-meta">
          <span className="eyebrow on-dark">health &middot; {bandWord(health.overall)}</span>
          <p className="server-name display">{server.name ?? "(unnamed server)"}</p>
          <p className="server-sub mono">
            {server.version ? `${server.version} · ` : ""}
            {report.target}
          </p>
        </div>
      </div>

      <div className="score-halves">
        <Half
          label="lint"
          value={String(health.lint_score)}
          detail={`${health.errors ?? 0} err · ${health.warnings ?? 0} warn`}
          band={bandVar(health.lint_score)}
        />
        <Half
          label="selection"
          value={lintOnly ? "—" : `${health.eval_score}%`}
          detail={lintOnly ? "no eval suite" : `${selCorrect} / ${selTotal} prompts`}
          band={lintOnly ? "var(--faint)" : bandVar(health.eval_score ?? 0)}
        />
      </div>
    </section>
  );
}

function Half({
  label,
  value,
  detail,
  band,
}: {
  label: string;
  value: string;
  detail: string;
  band: string;
}) {
  return (
    <div className="half">
      <span className="eyebrow on-dark">{label}</span>
      <span className="half-value display tnum" style={{ color: band }}>
        {value}
      </span>
      <span className="half-detail mono">{detail}</span>
    </div>
  );
}
