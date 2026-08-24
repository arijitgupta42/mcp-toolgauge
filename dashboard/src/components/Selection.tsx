import { useMemo } from "react";
import type { CiReport, ConfusionCell, ToolScore } from "../types";
import { bandVar, pct } from "../lib/score";
import { NOTHING, buildMatrix, describeConfusion, notableConfusions } from "../lib/matrix";

/*
 * The confusion matrix, given the room it never had in a terminal. `report/eval.py` says as
 * much itself -- it drops the "went instead to" column entirely below 24 characters of width.
 * Here the whole grid is the point: a row per tool the traffic was meant for, a column per
 * tool that captured some, the diagonal (correct) in the lime accent and everything off it in
 * a warm ramp, so stolen traffic is the thing your eye lands on. The per-tool bars and the
 * sentences underneath say the same thing two more ways, worst first and then in prose.
 */
export function Selection({ report }: { report: CiReport }) {
  const scores = report.eval?.scores;

  const matrix = useMemo(
    () => buildMatrix(scores?.confusion ?? []),
    [scores?.confusion],
  );
  const notable = useMemo(
    () => notableConfusions(scores?.confusion ?? []),
    [scores?.confusion],
  );

  if (!report.eval || !scores || (scores.selection_total ?? 0) === 0) {
    return (
      <div className="empty card">
        <p className="empty-title display">No selection was measured.</p>
        <p className="muted">
          This report was scored on lint alone. Draft a suite with{" "}
          <code className="tok">mcpcheckup eval &lt;server&gt; --init</code>, commit it, and{" "}
          <code className="tok">ci</code> will measure whether a model actually picks the right
          tool.
        </p>
      </div>
    );
  }

  const rates: Array<[string, number, number]> = [
    ["positives", scores.positive_correct ?? 0, scores.positive_total ?? 0],
    ["siblings", scores.sibling_correct ?? 0, scores.sibling_total ?? 0],
    ["abstention", scores.abstention_correct ?? 0, scores.abstention_total ?? 0],
    ["arguments", scores.argument_correct ?? 0, scores.argument_total ?? 0],
  ];

  const perTool = [...(scores.per_tool ?? [])].sort(
    (a, b) => a.correct / (a.total || 1) - b.correct / (b.total || 1) || b.total - a.total,
  );

  return (
    <div>
      <div className="rate-row">
        {rates.map(([label, correct, total]) => (
          <div className="rate-tile" key={label}>
            <span className="eyebrow">{label}</span>
            <span className="rate-val display tnum">
              {total ? `${pct(correct / total)}%` : "—"}
            </span>
            <span className="rate-sub mono">
              {correct}/{total}
            </span>
          </div>
        ))}
      </div>

      <div className="section-label">
        <span className="eyebrow">confusion</span>
        <h2>Where each tool&rsquo;s traffic actually went</h2>
      </div>
      <Heatmap matrix={matrix} />
      <Legend />

      <div className="section-label">
        <span className="eyebrow">per tool</span>
        <h2>Hit rate, worst first</h2>
      </div>
      <div className="card bars">
        {perTool.map((t) => (
          <ToolBar key={t.tool} score={t} />
        ))}
      </div>

      {notable.length > 0 && (
        <>
          <div className="section-label">
            <span className="eyebrow">the cost</span>
            <h2>Traffic one tool is taking from another</h2>
          </div>
          <ul className="steal-list">
            {notable.map((cell, i) => (
              <li key={i}>{sentence(cell)}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Heatmap({ matrix }: { matrix: ReturnType<typeof buildMatrix> }) {
  const { rows, cols } = matrix;
  const template = `minmax(120px, max-content) repeat(${cols.length}, minmax(52px, 1fr))`;

  return (
    <div className="card heatmap-wrap">
      <div className="heatmap" style={{ gridTemplateColumns: template }}>
        <div className="hm-corner" />
        {cols.map((c) => (
          <div className="hm-col mono" key={c} title={c}>
            {c === NOTHING ? "∅" : c}
          </div>
        ))}

        {rows.map((r) => (
          <Row key={r} row={r} cols={cols} at={matrix.at} />
        ))}
      </div>
    </div>
  );
}

function Row({
  row,
  cols,
  at,
}: {
  row: string;
  cols: string[];
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
        const background = !cell
          ? "transparent"
          : diagonal
            ? `rgba(178, 235, 118, ${0.25 + 0.75 * share})`
            : nothing
              ? `rgba(var(--nothing), ${0.12 + 0.6 * share})`
              : `rgba(var(--steal), ${0.15 + 0.75 * share})`;
        const cls = ["hm-cell"];
        if (diagonal) cls.push("diag");
        if (cell && !diagonal && !nothing && share >= 0.2) cls.push("steal");
        return (
          <div
            className={cls.join(" ")}
            key={c}
            style={{ background }}
            title={
              cell
                ? `${cell.count} of the prompts meant for ${row} → ${nothing ? "no tool" : c}`
                : ""
            }
          >
            {cell ? <span className="tnum">{pct(share)}</span> : ""}
          </div>
        );
      })}
    </>
  );
}

function Legend() {
  return (
    <div className="legend">
      <span className="legend-item">
        <span className="swatch" style={{ background: "rgba(178,235,118,0.85)" }} /> correct
      </span>
      <span className="legend-item">
        <span className="swatch" style={{ background: "rgba(var(--steal),0.7)" }} /> taken by
        another tool
      </span>
      <span className="legend-item">
        <span className="swatch" style={{ background: "rgba(var(--nothing),0.5)" }} /> ∅ called
        nothing
      </span>
    </div>
  );
}

function ToolBar({ score }: { score: ToolScore }) {
  const frac = score.total ? score.correct / score.total : 0;
  const percent = pct(frac);
  return (
    <div className="bar-row">
      <span className="bar-name mono" title={score.tool}>
        {score.tool}
      </span>
      <div className="bar-track">
        <div
          className="bar-fill"
          style={{ width: `${Math.max(2, percent)}%`, background: bandVar(percent) }}
        />
      </div>
      <span className="bar-val mono tnum">{percent}%</span>
      <span className="bar-sub mono">
        {score.correct}/{score.total}
      </span>
    </div>
  );
}

/** describeConfusion, with the two tool names picked out as tokens. */
function sentence(cell: ConfusionCell) {
  const text = describeConfusion(cell);
  const parts = text.split(/(\b\w[\w-]*\b)/);
  const names = new Set([cell.selected, cell.expected]);
  return parts.map((part, i) =>
    names.has(part) ? (
      <code className="tok" key={i}>
        {part}
      </code>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}
