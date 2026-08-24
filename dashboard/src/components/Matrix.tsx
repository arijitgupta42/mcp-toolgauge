import { useMemo } from "react";
import type { CiReport, ConfusionCell, ToolScore } from "../types";
import { bandVar, pct } from "../lib/score";
import { NOTHING, buildMatrix, describeConfusion, notableConfusions } from "../lib/matrix";

/*
 * Where each tool's traffic actually went.
 *
 * The terminal cannot draw this -- report/eval.py drops the "went instead to" column entirely
 * below 24 characters of width -- so the grid is the reason this dashboard exists at all. A
 * row per tool the prompts were meant for, a column per tool that captured any of them; the
 * diagonal is correct and everything off it is traffic one tool is taking from another.
 *
 * Shares are normalised across the row, so a cell is a fraction of the prompts meant for that
 * tool. That is what makes "search_users captures 88% of the prompts meant for ticket2" true
 * as written, and it is why adding an unrelated tool cannot move an existing pair's number.
 */
export function Matrix({ report }: { report: CiReport }) {
  const scores = report.eval?.scores;
  const cells = scores?.confusion ?? [];

  const grid = useMemo(() => buildMatrix(cells), [cells]);
  const notable = useMemo(() => notableConfusions(cells), [cells]);

  const perTool = useMemo(
    () =>
      [...(scores?.per_tool ?? [])].sort(
        (a, b) => a.correct / (a.total || 1) - b.correct / (b.total || 1) || b.total - a.total,
      ),
    [scores?.per_tool],
  );

  const head = (
    <div className="sec-head">
      <div>
        <span className="n">02</span>
        <h2 className="say">
          Where each tool&rsquo;s traffic <span className="dim">actually went</span>
        </h2>
      </div>
      {report.eval && <span className="cap mono">{report.eval.model}</span>}
    </div>
  );

  if (!report.eval || !scores || (scores.selection_total ?? 0) === 0) {
    return (
      <section className="band" id="selection">
        {head}
        <div className="nothing">
          <p className="say">
            Nothing was measured. <span className="dim">This report was scored on lint alone.</span>
          </p>
          <p className="how">
            Draft a suite with <code className="tok">mcp-toolgauge eval &lt;server&gt; --init</code>,
            edit the cases by hand, and commit them. From then on{" "}
            <code className="tok">ci</code> replays the recorded run offline and tells you
            whether a model actually picks the tool you meant.
          </p>
        </div>
      </section>
    );
  }

  const rates: ReadonlyArray<readonly [string, number, number, string]> = [
    ["Positives", scores.positive_correct ?? 0, scores.positive_total ?? 0, "one obvious tool"],
    ["Siblings", scores.sibling_correct ?? 0, scores.sibling_total ?? 0, "two plausible tools"],
    [
      "Abstention",
      scores.abstention_correct ?? 0,
      scores.abstention_total ?? 0,
      "no tool should fire",
    ],
    ["Arguments", scores.argument_correct ?? 0, scores.argument_total ?? 0, "call was well-formed"],
  ];

  return (
    <section className="band" id="selection">
      {head}

      <div className="wall" style={{ ["--cols" as string]: 4 }}>
        {rates.map(([k, correct, total, note]) => (
          <div className="cell" key={k}>
            <span className="k">{k}</span>
            <span className="v tnum">
              {total ? pct(correct / total) : "—"}
              {total > 0 && <span className="u">%</span>}
            </span>
            <span className="s">
              {correct} of {total} · {note}
            </span>
          </div>
        ))}
      </div>

      {/* A scrollable region, so a keyboard user can reach the far columns of a wide grid. */}
      <div className="hm-scroll" role="region" aria-label="Tool selection confusion matrix" tabIndex={0}>
        <div
          className="hm"
          style={{
            gridTemplateColumns: `minmax(140px, max-content) repeat(${grid.cols.length}, minmax(48px, 1fr))`,
          }}
        >
          <div className="hm-corner" />
          {grid.cols.map((c) => (
            <div className="hm-col mono" key={c} title={c}>
              {c === NOTHING ? "called nothing" : c}
            </div>
          ))}

          {grid.rows.map((r) => (
            <MatrixRow key={r} row={r} cols={grid.cols} at={grid.at} />
          ))}
        </div>
      </div>

      <div className="hm-legend">
        <span className="item">
          <i style={{ background: "rgba(var(--correct),0.75)" }} /> went to the right tool
        </span>
        <span className="item">
          <i style={{ background: "rgba(var(--steal),0.65)" }} /> taken by another tool
        </span>
        <span className="item">
          <i style={{ background: "rgba(var(--nothing),0.45)" }} /> no tool called at all
        </span>
      </div>

      {notable.length > 0 && (
        <>
          <div className="sub-head">
            <h3 className="say">
              The traffic one tool <span className="dim">is taking from another</span>
            </h3>
          </div>
          {notable.map((cell, i) => (
            <div className="steal" key={`${cell.expected}-${cell.selected ?? ""}`}>
              <span className="idx">{String(i + 1).padStart(2, "0")}</span>
              <p>{sentence(cell)}</p>
            </div>
          ))}
        </>
      )}

      <div className="sub-head">
        <h3 className="say">
          Hit rate, <span className="dim">worst first</span>
        </h3>
      </div>
      {perTool.map((t) => (
        <Hit key={t.tool} score={t} />
      ))}
    </section>
  );
}

function MatrixRow({
  row,
  cols,
  at,
}: {
  row: string;
  cols: readonly string[];
  at: (r: string, c: string) => ConfusionCell | undefined;
}) {
  return (
    <>
      <div className="hm-row mono" title={row}>
        {row}
      </div>
      {cols.map((c) => {
        const cell = at(row, c);
        const share = cell?.share ?? 0;
        const diagonal = row === c;
        const nothing = c === NOTHING;
        const ink = diagonal ? "correct" : nothing ? "nothing" : "steal";
        const alpha = diagonal ? 0.16 + 0.62 * share : nothing ? 0.1 + 0.55 * share : 0.14 + 0.72 * share;

        const cls = ["hm-cell"];
        if (cell) cls.push("filled");
        if (diagonal) cls.push("diag");

        return (
          <div
            key={c}
            className={cls.join(" ")}
            style={{ background: cell ? `rgba(var(--${ink}), ${alpha})` : "transparent" }}
            title={cell ? describe(cell, row, c, nothing) : ""}
            aria-label={cell ? describe(cell, row, c, nothing) : undefined}
          >
            {cell ? <span className="tnum">{pct(share)}</span> : ""}
          </div>
        );
      })}
    </>
  );
}

function Hit({ score }: { score: ToolScore }) {
  const percent = score.total ? pct(score.correct / score.total) : 0;
  return (
    <div className="hit">
      <span className="who" title={score.tool}>
        {score.tool}
      </span>
      <span className="track">
        <span
          className="fill"
          style={{
            width: `${Math.max(1.5, percent)}%`,
            ["--band" as string]: bandVar(percent),
          }}
        />
      </span>
      <span className="num tnum">
        {percent}%
        <small>
          {score.correct}/{score.total}
        </small>
      </span>
    </div>
  );
}

function describe(cell: ConfusionCell, row: string, col: string, nothing: boolean): string {
  const went = nothing ? "no tool at all" : col;
  return `${cell.count} of the prompts meant for ${row} (${pct(cell.share)}%) went to ${went}`;
}

/** describeConfusion, with the numbers and the two tool names inked out of the grey. */
function sentence(cell: ConfusionCell) {
  const text = describeConfusion(cell);
  const names = new Set([cell.selected, cell.expected]);
  // `88%` has to be one token, or the numeral inks and the sign stays grey behind it.
  return text.split(/(\d+%|[\w-]+)/).map((part, i) => {
    const bold = names.has(part) || /^\d+%$/.test(part);
    return bold ? <b key={i}>{part}</b> : <span key={i}>{part}</span>;
  });
}
