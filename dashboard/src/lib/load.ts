/*
 * Where a report comes from. Three sources, one backend-free rule: nothing is ever uploaded.
 *
 *  - the bundled demo reports, shipped in public/reports/ and fetched from the app's own
 *    origin;
 *  - a `?report=<url>` the browser fetches directly -- a raw GitHub URL works untouched,
 *    because raw.githubusercontent.com sends `Access-Control-Allow-Origin: *`, which is the
 *    same publish-a-raw-URL move the shields.io badge already relies on; and
 *  - text a user pastes or a file they drop, for a server whose tool list they would rather
 *    not put on the public internet.
 *
 * A parsed report is shape-checked just enough to fail loudly on the wrong file rather than
 * throwing deep inside a renderer. It is not full validation -- the producer is our own
 * Pydantic model -- just the few fields whose absence means "this is not a ci --json report".
 */

import type { CiReport } from "../types";

export const DEMOS = ["goodserver", "badserver"] as const;
export type DemoName = (typeof DEMOS)[number];

export function isCiReport(value: unknown): value is CiReport {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.target === "string" &&
    typeof v.health === "object" &&
    v.health !== null &&
    typeof (v.health as Record<string, unknown>).overall === "number" &&
    typeof v.lint === "object" &&
    v.lint !== null
  );
}

function parseReport(text: string): CiReport {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error("That is not valid JSON. Paste the output of `mcp-toolgauge ci --json`.");
  }
  if (!isCiReport(value)) {
    throw new Error(
      "That JSON is not a mcp-toolgauge report -- it has no health score. " +
        "Produce one with `mcp-toolgauge ci <server> --json`.",
    );
  }
  return value;
}

export async function loadDemo(name: DemoName): Promise<CiReport> {
  const url = `${import.meta.env.BASE_URL}reports/${name}.json`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Could not load the ${name} demo (${res.status}).`);
  return parseReport(await res.text());
}

export async function loadUrl(url: string): Promise<CiReport> {
  let res: Response;
  try {
    res = await fetch(url);
  } catch {
    // A CORS rejection lands here with no detail the browser will share, so the message
    // names the one host that is known to work rather than guessing at the cause.
    throw new Error(
      "Could not fetch that URL. It must be reachable and CORS-enabled -- a " +
        "raw.githubusercontent.com link to a committed report is the reliable option.",
    );
  }
  if (!res.ok) throw new Error(`That URL returned ${res.status}.`);
  return parseReport(await res.text());
}

export function loadText(text: string): CiReport {
  return parseReport(text);
}
