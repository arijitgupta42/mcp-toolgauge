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
 *
 * Laid out as a white card in a tray with three inset tiles, which is how mora.com draws a
 * metric row. The emphasis is carried by the size of the numeral and the band colour, not by
 * an inverted panel -- there is no dark ground anywhere on that site, and there is none here.
 */
export function Scorecard({ report }: { report: CiReport }) {
  const { health, server, eval: evaluation } = report;
  const selection = evaluation?.scores;
  const selCorrect = selection?.selection_correct ?? 0;
  const selTotal = selection?.selection_total ?? 0;
  const lintOnly = health.eval_score == null;

  return (
    <section className="scorecard tray">
      <div className="scorecard-inner">
        <div className="scorecard-head">
          <div style={{ minWidth: 0 }}>
            <p className="server-name">{server.name ?? "(unnamed server)"}</p>
            <p className="server-sub mono">
              {server.version ? `${server.version} · ` : ""}
              {report.target}
            </p>
          </div>
          <span
            className="band-pill"
            style={{ ["--band" as string]: bandVar(health.overall) }}
          >
            <span className="dot" />
            {bandWord(health.overall)}
          </span>
        </div>

        <div className="score-tiles">
          <Tile
            hero
            label="Health"
            value={String(health.overall)}
            suffix="/100"
            detail="½ lint · ½ selection"
            band={bandVar(health.overall)}
          />
          <Tile
            label="Lint"
            value={String(health.lint_score)}
            detail={`${health.errors ?? 0} errors · ${health.warnings ?? 0} warnings`}
            band={bandVar(health.lint_score)}
          />
          <Tile
            label="Selection"
            value={lintOnly ? "—" : `${health.eval_score}%`}
            detail={lintOnly ? "no eval suite" : `${selCorrect} of ${selTotal} prompts`}
            band={lintOnly ? "var(--faint)" : bandVar(health.eval_score ?? 0)}
          />
        </div>
      </div>
    </section>
  );
}

function Tile({
  label,
  value,
  suffix,
  detail,
  band,
  hero = false,
}: {
  label: string;
  value: string;
  suffix?: string;
  detail: string;
  band: string;
  hero?: boolean;
}) {
  return (
    <div className={hero ? "tile hero" : "tile"} style={{ ["--band" as string]: band }}>
      <span className="tile-label">{label}</span>
      <span className="tile-value tnum">
        {value}
        {suffix && <span className="tile-max">{suffix}</span>}
      </span>
      <span className="tile-detail">{detail}</span>
    </div>
  );
}
