import { useEffect, useState } from "react";
import type { DemoName } from "../lib/load";

export type Source =
  | { kind: "demo"; demo: DemoName }
  | { kind: "url"; url: string }
  | { kind: "file"; name: string };

export interface SectionLink {
  id: string;
  n: string;
  label: string;
}

/*
 * The page chrome: the near-black strip, the sticky rail, and the drawer the rail opens.
 *
 * The rail carries two jobs that used to be two separate bands of the page -- saying where
 * you are in the report, and choosing which report you are reading. Putting both in the one
 * strip is what lets the document below it start with the verdict instead of with furniture.
 *
 * The privacy line in the drawer is not decoration. A URL is fetched by the browser and a
 * dropped file is read in the browser; there is no server to send either to. That is what
 * makes it safe to point this at a private tool list, and it is worth saying plainly.
 */
export function Rail({
  source,
  sections,
  active,
  busy,
  error,
  onDemo,
  onUrl,
}: {
  source: Source;
  sections: readonly SectionLink[];
  active: string;
  busy: boolean;
  error: string | null;
  onDemo: (name: DemoName) => void;
  onUrl: (url: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");

  // A failed load has to be visible even if the drawer that caused it has been shut, and the
  // drawer is where the retry lives -- so an error opens it rather than being announced
  // somewhere the user then has to go looking for the input again.
  useEffect(() => {
    if (error) setOpen(true);
  }, [error]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = url.trim();
    if (trimmed) onUrl(trimmed);
  };

  return (
    <>
      <div className="strip">
        <div className="strip-in">
          <span>
            <b>mcp-toolgauge</b> &mdash; find out why your MCP server&rsquo;s tools don&rsquo;t
            get called
          </span>
          <a
            href="https://github.com/arijitgupta42/mcp-toolgauge"
            target="_blank"
            rel="noreferrer"
          >
            Read the docs <span aria-hidden="true">&rsaquo;</span>
          </a>
        </div>
      </div>

      <div className="rail">
        <div className="rail-in">
          <a className="mark" href="./">
            <span className="glyph" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            toolgauge
          </a>

          <nav className="rail-nav" aria-label="Report sections">
            {sections.map((s) => (
              <a
                key={s.id}
                href={`#${s.id}`}
                className={active === s.id ? "rail-link here" : "rail-link"}
                aria-current={active === s.id ? "true" : undefined}
              >
                <span className="n">{s.n}</span>
                <span className="lab">{s.label}</span>
              </a>
            ))}
          </nav>

          <div className="rail-right">
            <div className="switch" role="group" aria-label="Demo report">
              {(["goodserver", "badserver"] as const).map((name) => {
                const live = source.kind === "demo" && source.demo === name;
                return (
                  <button
                    key={name}
                    className={live ? "pill on" : "pill"}
                    onClick={() => onDemo(name)}
                    disabled={busy}
                    aria-pressed={live}
                  >
                    {name.replace("server", "")}
                  </button>
                );
              })}
            </div>
            <button
              className="pill"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
            >
              {sourceWord(source)}
            </button>
          </div>
        </div>
      </div>

      {open && (
        <div className="drawer">
          <div className="drawer-in">
            <form onSubmit={submit}>
              <input
                type="url"
                inputMode="url"
                placeholder="https://raw.githubusercontent.com/…/report.json"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                aria-label="Report URL"
              />
              <button className="btn" type="submit" disabled={busy || !url.trim()}>
                Load
              </button>
            </form>
            <p className="drawer-note">
              Or drop a <code className="tok">mcp-toolgauge ci --json</code> file anywhere on
              this page. Both are read in your browser &mdash; there is no server here, so
              nothing you load is uploaded anywhere.
            </p>
            {error && <p className="err">{error}</p>}
          </div>
        </div>
      )}
    </>
  );
}

function sourceWord(source: Source): string {
  if (source.kind === "url") return "loaded from URL";
  if (source.kind === "file") return source.name;
  return "load a report";
}
