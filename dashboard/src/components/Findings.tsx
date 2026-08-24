import { useMemo, useState } from "react";
import type { CiReport, Finding, Severity } from "../types";

/*
 * The lint findings, grouped the way a maintainer reads them: by where they are (the server,
 * then a tool, then a tool's parameter), because you fix a server one tool at a time. Every
 * row carries its suggestion in full and never behind a click -- the suggestion is the product,
 * the message only says what is wrong. The rule id links to its docs page, which is where the
 * "why it matters" lives.
 */

const ORDER: Severity[] = ["error", "warning", "info"];
const DOCS = "https://github.com/arijitgupta42/mcp-toolgauge/blob/main/docs/rules";

const sevColor: Record<Severity, string> = {
  error: "var(--sev-error)",
  warning: "var(--sev-warning)",
  info: "var(--sev-info)",
};

function locationOf(f: Finding): string {
  if (!f.tool) return "(server)";
  return f.parameter ? `${f.tool}.${f.parameter}` : f.tool;
}

function groupKey(f: Finding): string {
  return f.tool ?? "(server)";
}

export function Findings({ report }: { report: CiReport }) {
  const findings = report.lint.findings ?? [];
  const [active, setActive] = useState<Set<Severity>>(new Set());

  const counts = useMemo(() => {
    const c: Record<Severity, number> = { error: 0, warning: 0, info: 0 };
    for (const f of findings) c[f.severity] += 1;
    return c;
  }, [findings]);

  const shown = active.size === 0 ? findings : findings.filter((f) => active.has(f.severity));

  const groups = useMemo(() => {
    const byTool = new Map<string, Finding[]>();
    for (const f of shown) {
      const key = groupKey(f);
      const list = byTool.get(key) ?? [];
      list.push(f);
      byTool.set(key, list);
    }
    // (server) first, then tools alphabetically -- a stable reading order.
    return [...byTool.entries()].sort(([a], [b]) => {
      if (a === "(server)") return -1;
      if (b === "(server)") return 1;
      return a.localeCompare(b);
    });
  }, [shown]);

  const toggle = (sev: Severity) => {
    const next = new Set(active);
    next.has(sev) ? next.delete(sev) : next.add(sev);
    setActive(next);
  };

  if (findings.length === 0) {
    return (
      <div className="empty card">
        <span className="empty-mark" style={{ color: "var(--band-brightgreen)" }}>
          ✓
        </span>
        <p className="empty-title display">No findings.</p>
        <p className="muted">
          Every tool on this server passed all {report.lint.tool_count}-tool&rsquo;s worth of
          checks. That is what a clean lint looks like.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="filter-row">
        {ORDER.map((sev) => (
          <button
            key={sev}
            className={active.has(sev) ? "chip filter on" : "chip filter"}
            onClick={() => toggle(sev)}
            aria-pressed={active.has(sev)}
            disabled={counts[sev] === 0}
          >
            <span className="dot" style={{ background: sevColor[sev] }} />
            {sev}
            <span className="tnum">{counts[sev]}</span>
          </button>
        ))}
        {active.size > 0 && (
          <button className="chip clear" onClick={() => setActive(new Set())}>
            clear filter
          </button>
        )}
      </div>

      {groups.map(([tool, list]) => (
        <div className="finding-group" key={tool}>
          <div className="group-head">
            <span className="mono group-name">{tool}</span>
            <span className="group-line" />
            <span className="eyebrow tnum">{list.length}</span>
          </div>
          {ORDER.flatMap((sev) =>
            list
              .filter((f) => f.severity === sev)
              .map((f, i) => <Row key={`${f.rule}-${locationOf(f)}-${i}`} f={f} />),
          )}
        </div>
      ))}
    </div>
  );
}

function Row({ f }: { f: Finding }) {
  return (
    <div className="finding card">
      <div className="finding-top">
        <a
          className="rule-id mono"
          href={`${DOCS}/${f.rule}.md`}
          target="_blank"
          rel="noreferrer"
          style={{ borderColor: sevColor[f.severity] }}
        >
          {f.rule}
        </a>
        <span className="sev-tag mono" style={{ color: sevColor[f.severity] }}>
          {f.severity}
        </span>
        {f.parameter && <span className="loc mono">{f.parameter}</span>}
      </div>
      <p className="finding-msg">{renderBackticks(f.message)}</p>
      <p className="finding-fix">
        <span className="eyebrow">fix</span> {renderBackticks(f.suggestion)}
      </p>
    </div>
  );
}

/** Messages carry `identifiers` in backticks, the same as the terminal. Pick them out. */
function renderBackticks(text: string) {
  const parts = text.split("`");
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <code className="tok" key={i}>
        {part}
      </code>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}
