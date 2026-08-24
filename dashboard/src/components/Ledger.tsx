import { useMemo, useState } from "react";
import type { CiReport, Finding, Severity } from "../types";

/*
 * The lint findings, as a ledger: one ruled line per finding, grouped by the tool it belongs
 * to, with the tool's name in a header that sticks under the rail while you read its rows.
 * A server is fixed one tool at a time, and 74 findings are only tractable if the reader can
 * see where one tool ends and the next begins without counting.
 *
 * Three columns, always in the same order: what the rule is, what is wrong, what to do about
 * it. The fix column is the product -- the message only names the problem -- so it gets equal
 * width and is never behind a click. The rule id links to its docs page, which is where the
 * "why it matters" argument lives.
 */

const ORDER: readonly Severity[] = ["error", "warning", "info"];
const DOCS = "https://github.com/arijitgupta42/mcp-toolgauge/blob/main/docs/rules";

const SEV_COLOR: Record<Severity, string> = {
  error: "var(--sev-error)",
  warning: "var(--sev-warning)",
  info: "var(--sev-info)",
};

export function Ledger({ report }: { report: CiReport }) {
  const findings = report.lint.findings ?? [];
  const [only, setOnly] = useState<ReadonlySet<Severity>>(new Set());

  const counts = useMemo(() => {
    const c: Record<Severity, number> = { error: 0, warning: 0, info: 0 };
    for (const f of findings) c[f.severity] += 1;
    return c;
  }, [findings]);

  const shown = useMemo(
    () => (only.size === 0 ? findings : findings.filter((f) => only.has(f.severity))),
    [findings, only],
  );

  const groups = useMemo(() => {
    const byTool = new Map<string, Finding[]>();
    for (const f of shown) {
      const key = f.tool ?? "(server)";
      const list = byTool.get(key) ?? [];
      list.push(f);
      byTool.set(key, list);
    }
    // The server's own findings first, then tools alphabetically: a stable reading order
    // that does not shuffle when a filter is applied.
    return [...byTool.entries()].sort(([a], [b]) => {
      if (a === "(server)") return -1;
      if (b === "(server)") return 1;
      return a.localeCompare(b);
    });
  }, [shown]);

  const toggle = (sev: Severity) => {
    const next = new Set(only);
    if (next.has(sev)) next.delete(sev);
    else next.add(sev);
    setOnly(next);
  };

  return (
    <section className="band" id="findings">
      <div className="sec-head">
        <div>
          <span className="n">01</span>
          <h2 className="say">
            What lint found, <span className="dim">tool by tool</span>
          </h2>
        </div>
        {findings.length > 0 && (
          <div className="sec-tools">
            {ORDER.map((sev) => (
              <button
                key={sev}
                className={only.has(sev) ? "pill on" : "pill"}
                onClick={() => toggle(sev)}
                aria-pressed={only.has(sev)}
                disabled={counts[sev] === 0}
              >
                <span className="dot" style={{ background: SEV_COLOR[sev] }} />
                {sev}
                <span className="tnum">{counts[sev]}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {findings.length === 0 ? (
        <div className="nothing">
          <p className="say">
            Nothing to fix. <span className="dim">All {report.lint.tool_count} tools pass every rule.</span>
          </p>
          <p className="how">
            That is what a clean lint looks like: every tool named for what it does, described
            in a sentence a model can act on, with its parameters documented and its side
            effects annotated. The other half of the score is below.
          </p>
        </div>
      ) : (
        groups.map(([tool, list]) => (
          <div key={tool}>
            <div className="grp">
              <span className="who">{tool}</span>
              <span className="how-many tnum">
                {list.length} {list.length === 1 ? "finding" : "findings"}
              </span>
            </div>
            {ORDER.flatMap((sev) =>
              list
                .filter((f) => f.severity === sev)
                .map((f, i) => <Line key={`${f.rule}-${f.parameter ?? ""}-${i}`} f={f} />),
            )}
          </div>
        ))
      )}
    </section>
  );
}

function Line({ f }: { f: Finding }) {
  return (
    <article className="f" style={{ ["--sev" as string]: SEV_COLOR[f.severity] }}>
      <div className="f-id">
        <a className="f-rule" href={`${DOCS}/${f.rule}.md`} target="_blank" rel="noreferrer">
          {f.rule}
        </a>
        <span className="f-sev">
          <i />
          {f.severity}
        </span>
        {f.parameter && <span className="where">{f.parameter}</span>}
      </div>
      <div className="f-msg">
        <p>{ticks(f.message)}</p>
      </div>
      <div className="f-fix">
        <span className="lab">Fix</span>
        <p>{ticks(f.suggestion)}</p>
      </div>
    </article>
  );
}

/** Messages carry `identifiers` in backticks, exactly as the terminal renderer does. */
function ticks(text: string) {
  return text.split("`").map((part, i) =>
    i % 2 === 1 ? (
      <code className="tok" key={i}>
        {part}
      </code>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}
