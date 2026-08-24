import { type DragEvent, useCallback, useEffect, useState } from "react";
import type { CiReport } from "./types";
import { loadDemo, loadText, loadUrl } from "./lib/load";
import { useSpy } from "./spy";
import { Rail, type SectionLink, type Source } from "./components/Rail";
import { Verdict } from "./components/Verdict";
import { Ledger } from "./components/Ledger";
import { Matrix } from "./components/Matrix";
import { Trend } from "./components/Trend";

/*
 * One report, read top to bottom.
 *
 * The three parts of a report are sections of a single document rather than tabs, and that is
 * the load-bearing decision here. Tabs made the reader choose which third to look at before
 * they knew what any of it said, and hid two thirds of the evidence behind a click -- on a
 * page whose whole point is that a lint finding and a confusion cell are usually the same problem
 * seen twice. Scrolling puts them in the same view; the rail just says where you are.
 */

const SECTIONS: readonly SectionLink[] = [
  { id: "findings", n: "01", label: "Findings" },
  { id: "selection", n: "02", label: "Selection" },
  { id: "history", n: "03", label: "History" },
];

const RAIL_H = 56;

export function App() {
  const [report, setReport] = useState<CiReport | null>(null);
  const [source, setSource] = useState<Source>({ kind: "demo", demo: "goodserver" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [dropping, setDropping] = useState(false);

  const active = useSpy(
    SECTIONS.map((s) => s.id),
    RAIL_H,
  );

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
    if (url) void show({ kind: "url", url }, () => loadUrl(url));
    else void show({ kind: "demo", demo: "goodserver" }, () => loadDemo("goodserver"));
  }, [show]);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDropping(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      void file
        .text()
        .then((text) => show({ kind: "file", name: file.name }, () => loadText(text)));
    }
  };

  return (
    <div
      className={dropping ? "page dropping" : "page"}
      onDragOver={(e) => {
        e.preventDefault();
        setDropping(true);
      }}
      onDragLeave={(e) => {
        // Only when the pointer actually leaves the window, not on every child boundary.
        if (e.relatedTarget === null) setDropping(false);
      }}
      onDrop={onDrop}
    >
      <Rail
        source={source}
        sections={SECTIONS}
        active={active}
        busy={busy}
        error={error}
        onDemo={(demo) => void show({ kind: "demo", demo }, () => loadDemo(demo))}
        onUrl={(url) => void show({ kind: "url", url }, () => loadUrl(url))}
      />

      <div className="frame">
        {report ? (
          <>
            <Verdict report={report} />
            <Ledger report={report} />
            <Matrix report={report} />
            <Trend report={report} />
          </>
        ) : (
          <div className="nothing">
            <p className="say">
              {busy ? (
                <>
                  Reading the report<span className="dim">…</span>
                </>
              ) : (
                <>
                  No report loaded. <span className="dim">Pick a demo above, or load your own.</span>
                </>
              )}
            </p>
          </div>
        )}

        <footer className="colophon">
          <span>
            Read straight out of a <code className="tok">mcp-toolgauge ci --json</code> report.
          </span>
          <span>Everything is parsed in your browser; nothing is uploaded.</span>
          <a href="https://github.com/arijitgupta42/mcp-toolgauge" target="_blank" rel="noreferrer">
            Source &amp; docs
          </a>
        </footer>
      </div>

      <div className="tail" />
    </div>
  );
}
