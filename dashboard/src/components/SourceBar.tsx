import { type DragEvent, useState } from "react";
import type { DemoName } from "../lib/load";

export type Source =
  | { kind: "demo"; demo: DemoName }
  | { kind: "url"; url: string }
  | { kind: "file"; name: string };

/*
 * Choosing where the report comes from, and saying where the one on screen came from. The
 * privacy line is not decoration: a URL is fetched by the browser and a dropped file is read
 * in the browser, and neither is ever sent to a server -- there is no server -- so a maintainer
 * can point this at a private tool list without it leaving their machine.
 */
export function SourceBar({
  source,
  onDemo,
  onUrl,
  onText,
  error,
  busy,
}: {
  source: Source;
  onDemo: (name: DemoName) => void;
  onUrl: (url: string) => void;
  onText: (text: string, name: string) => void;
  error: string | null;
  busy: boolean;
}) {
  const [url, setUrlValue] = useState("");
  const [dragging, setDragging] = useState(false);

  const submitUrl = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = url.trim();
    if (trimmed) onUrl(trimmed);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) file.text().then((text) => onText(text, file.name));
  };

  return (
    <section
      className={dragging ? "sourcebar dragging" : "sourcebar"}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <div className="sourcebar-inner">
      <div className="source-row">
        <div className="segmented" role="group" aria-label="Demo report">
          {(["goodserver", "badserver"] as const).map((name) => {
            const active = source.kind === "demo" && source.demo === name;
            return (
              <button
                key={name}
                className={active ? "seg active" : "seg"}
                onClick={() => onDemo(name)}
                disabled={busy}
              >
                {name}
              </button>
            );
          })}
        </div>

        <form className="url-form" onSubmit={submitUrl}>
          <input
            className="url-input mono"
            type="url"
            inputMode="url"
            placeholder="…or a raw URL to a ci --json report"
            value={url}
            onChange={(e) => setUrlValue(e.target.value)}
            aria-label="Report URL"
          />
          <button className="btn" type="submit" disabled={busy || !url.trim()}>
            Load
          </button>
        </form>
      </div>

      <div className="source-foot">
        <span className="eyebrow">
          {source.kind === "demo"
            ? `Demo · ${source.demo}`
            : source.kind === "url"
              ? "Loaded from URL"
              : `Loaded · ${source.name}`}
        </span>
        <span className="drop-hint muted">
          Drop a <span className="mono">ci&nbsp;--json</span> file anywhere here. Nothing is
          uploaded.
        </span>
      </div>

      {error && <p className="source-error">{error}</p>}
      </div>
    </section>
  );
}
