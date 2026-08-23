/*
 * Turning a 0-100 score into the band it belongs to. This is a straight port of the ladder
 * in mcp_doctor/health.py (`_BANDS` / `color_for`), and the port is not incidental: the whole
 * value of the dashboard is that it agrees with the badge and the terminal about what a number
 * is worth. score.test.ts pins these boundaries against the Python so a change to one side
 * that is not mirrored on the other fails CI rather than shipping a dashboard that quietly
 * disagrees with the badge on the same repo.
 */

export type Band =
  | "brightgreen"
  | "green"
  | "yellowgreen"
  | "yellow"
  | "orange"
  | "red";

// Highest floor first, exactly as in health.py's _BANDS. A score at or above a floor takes
// that band; nothing matches means the worst one.
const BANDS: ReadonlyArray<readonly [number, Band]> = [
  [90, "brightgreen"],
  [75, "green"],
  [60, "yellowgreen"],
  [45, "yellow"],
  [30, "orange"],
];

export function scoreBand(score: number): Band {
  for (const [floor, band] of BANDS) {
    if (score >= floor) return band;
  }
  return "red";
}

/** The CSS custom property carrying a band's colour, e.g. `var(--band-orange)`. */
export function bandVar(score: number): string {
  return `var(--band-${scoreBand(score)})`;
}

/** A human word for a band, for the eyebrow beside the numeral. */
export function bandWord(score: number): string {
  const band = scoreBand(score);
  if (band === "brightgreen") return "healthy";
  if (band === "green") return "good";
  if (band === "yellowgreen") return "fair";
  if (band === "yellow") return "middling";
  if (band === "orange") return "poor";
  return "critical";
}

/** A percentage as an integer string, matching Rate.percent (round half to even is fine —
 *  the Python uses round(), and these are display-only). */
export function pct(fraction: number): number {
  return Math.round(fraction * 100);
}
