import { useCallback, useEffect, useState } from "react";
import type { CiReport } from "./types";
import { type DemoName, loadDemo, loadText, loadUrl } from "./lib/load";
import { Scorecard } from "./components/Scorecard";
import { SourceBar, type Source } from "./components/SourceBar";
import { Findings } from "./components/Findings";
import { Selection } from "./components/Selection";
import { History } from "./components/History";

type View = "findings" | "selection" | "history";

const VIEWS: ReadonlyArray<{ id: View; label: string }> = [
  { id: "findings", label: "Findings" },
  { id: "selection", label: "Selection" },
  { id: "history", label: "History" },
];

export function App() {
  const [report, setReport] = useState<CiReport | null>(null);
  const [source, setSource] = useState<Source>({ kind: "demo", demo: "goodserver" });
  const [view, setView] = useState<View>("findings");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  const show = useCallback(
    async (next: Source, load: () => Promise<CiReport> | CiReport) => {
      setBusy(true);
      setError(null);
      try {
        const loaded = await load();
        setReport(loaded);
        setSource(next);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  // First paint: honour ?report=<url>, else the good-server demo. Read once.
  useEffect(() => {
    const url = new URLSearchParams(window.location.search).get("report");
    if (url) {
      void show({ kind: "url", url }, () => loadUrl(url));
    } else {
      void show({ kind: "demo", demo: "goodserver" }, () => loadDemo("goodserver"));
    }
  }, [show]);

  const onDemo = (demo: DemoName) => show({ kind: "demo", demo }, () => loadDemo(demo));
  const onUrl = (url: string) => show({ kind: "url", url }, () => loadUrl(url));
  const onText = (text: string, name: string) =>
    show({ kind: "file", name }, () => loadText(text));

  const findingsCount = report?.lint.findings?.length ?? 0;

  return (
    <div className="shell">
      <header className="masthead">
        <span className="wordmark">
          <span className="mark" aria-hidden="true">
            M
          </span>
          mcp-toolgauge
        </span>
        <h1 className="tagline">
          Why your MCP server&rsquo;s tools{" "}
          <span className="rest">do &mdash; or don&rsquo;t &mdash; get called.</span>
        </h1>
        <p className="lede">
          Lint findings, the tool-selection confusion matrix, and health over time, read
          straight out of a <code className="tok">ci --json</code> report.
        </p>
      </header>

      <SourceBar
        source={source}
        onDemo={onDemo}
        onUrl={onUrl}
        onText={onText}
        error={error}
        busy={busy}
      />

      {report && (
        <>
          <Scorecard report={report} />

          <nav className="tabs" role="tablist" aria-label="Views">
            {VIEWS.map((v) => {
              const count =
                v.id === "findings" && findingsCount ? ` ${findingsCount}` : "";
              return (
                <button
                  key={v.id}
                  role="tab"
                  aria-selected={view === v.id}
                  className={view === v.id ? "tab active" : "tab"}
                  onClick={() => setView(v.id)}
                >
                  {v.label}
                  {count && <span className="tab-count tnum">{count}</span>}
                </button>
              );
            })}
          </nav>

          <main>
            {view === "findings" && <Findings report={report} />}
            {view === "selection" && <Selection report={report} />}
            {view === "history" && <History report={report} />}
          </main>
        </>
      )}

      <footer className="colophon">
        <span className="eyebrow">mcp-toolgauge</span>
        <span className="muted">
          Static report viewer &mdash; nothing you load here is uploaded anywhere.
        </span>
      </footer>
    </div>
  );
}
