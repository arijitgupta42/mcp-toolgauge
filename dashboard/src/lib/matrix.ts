/*
 * The confusion matrix, and the "steals this much" sentences under it.
 *
 * `notableConfusions` is a port of the function of the same name in mcp_toolgauge/eval/score.py,
 * and matrix.test.ts pins it against that function's rule cell for cell: an off-diagonal cell,
 * whose `selected` is a real tool (not the "called nothing" row), whose share is at least
 * 0.20, sorted by descending share then descending count then the two tool names, capped at
 * five. If the CLI's headline sentences and the dashboard's ever diverged, they would be
 * telling two stories about one report, so the rule lives in one shape in both languages and
 * is tested on both sides.
 */

import type { ConfusionCell } from "../types";

export const NOTABLE_SHARE = 0.2;
export const TOP_CONFUSIONS = 5;

export const NOTHING = "(nothing)";

function isDiagonal(cell: ConfusionCell): boolean {
  return cell.expected === (cell.selected ?? null);
}

/** The off-diagonal cells worth a sentence, biggest first. Mirrors eval/score.py exactly. */
export function notableConfusions(
  cells: ConfusionCell[],
  { minShare = NOTABLE_SHARE, limit = TOP_CONFUSIONS } = {},
): ConfusionCell[] {
  return cells
    .filter(
      (cell) =>
        !isDiagonal(cell) &&
        cell.selected != null &&
        cell.share >= minShare,
    )
    .sort(
      (a, b) =>
        b.share - a.share ||
        b.count - a.count ||
        a.expected.localeCompare(b.expected) ||
        (a.selected ?? "").localeCompare(b.selected ?? ""),
    )
    .slice(0, limit);
}

/** The one sentence the whole eval exists to print, for a single cell. */
export function describeConfusion(cell: ConfusionCell): string {
  const share = Math.round(cell.share * 100);
  return `${cell.selected} captures ${share}% of the prompts meant for ${cell.expected}.`;
}

export interface Matrix {
  rows: string[]; // expected tools, in first-seen order
  cols: string[]; // selected tools (real ones), plus NOTHING last if any cell has it
  at: (row: string, col: string) => ConfusionCell | undefined;
  hasNothing: boolean;
}

/**
 * Arrange the flat cell list into a grid: a row per expected tool, a column per tool that
 * ever captured traffic, with the "called nothing" column pushed to the end because a benign
 * miss should not sit between two real tools.
 */
export function buildMatrix(cells: ConfusionCell[]): Matrix {
  const rows: string[] = [];
  const cols: string[] = [];
  let hasNothing = false;
  const index = new Map<string, ConfusionCell>();

  const key = (row: string, col: string) => `${row}\u0000${col}`;

  for (const cell of cells) {
    if (!rows.includes(cell.expected)) rows.push(cell.expected);
    if (cell.selected == null) {
      hasNothing = true;
      index.set(key(cell.expected, NOTHING), cell);
    } else {
      if (!cols.includes(cell.selected)) cols.push(cell.selected);
      index.set(key(cell.expected, cell.selected), cell);
    }
  }

  // Stable, readable column order: the expected tools first (so the diagonal runs top-left
  // to bottom-right wherever it can), then any pure-thief tool that never had a row of its
  // own, then the nothing column.
  const ordered: string[] = [];
  for (const r of rows) if (cols.includes(r)) ordered.push(r);
  for (const c of cols) if (!ordered.includes(c)) ordered.push(c);
  if (hasNothing) ordered.push(NOTHING);

  return {
    rows,
    cols: ordered,
    hasNothing,
    at: (row, col) => index.get(key(row, col)),
  };
}
