import { describe, expect, it } from "vitest";
import type { ConfusionCell } from "../types";
import { buildMatrix, describeConfusion, notableConfusions } from "./matrix";

/*
 * notableConfusions is a port of the same function in mcp_doctor/eval/score.py, and these
 * tests are its contract, cell for cell: off-diagonal only, the "called nothing" row excluded,
 * share >= 0.20, sorted by descending share then descending count then the two names, top five.
 * The confusion sentence is the single output the whole eval exists to produce, so a drift
 * between the CLI's wording and the dashboard's is a real regression and fails here.
 */

function cell(
  expected: string,
  selected: string | null,
  count: number,
  share: number,
): ConfusionCell {
  return { expected, selected, count, share };
}

describe("notableConfusions", () => {
  it("keeps only off-diagonal, real-tool, share>=0.20 cells", () => {
    const cells = [
      cell("a", "a", 8, 0.8), // diagonal -> out
      cell("a", "b", 2, 0.2), // kept (exactly at threshold)
      cell("c", "d", 3, 0.19), // below threshold -> out
      cell("e", null, 4, 0.9), // called nothing -> out
      cell("f", "g", 5, 0.5), // kept
    ];
    const got = notableConfusions(cells);
    expect(got.map((c) => [c.expected, c.selected])).toEqual([
      ["f", "g"],
      ["a", "b"],
    ]);
  });

  it("sorts by share, then count, then names", () => {
    const cells = [
      cell("a", "x", 1, 0.5),
      cell("b", "y", 9, 0.5), // same share, higher count -> first
      cell("a", "w", 2, 0.9), // highest share -> before both
      cell("c", "z", 2, 0.9), // ties a->w on share and count; name breaks it
    ];
    const got = notableConfusions(cells);
    expect(got.map((c) => c.expected)).toEqual(["a", "c", "b", "a"]);
  });

  it("caps at five", () => {
    const cells = Array.from({ length: 8 }, (_, i) =>
      cell(`row${i}`, `col${i}`, 5, 0.5),
    );
    expect(notableConfusions(cells)).toHaveLength(5);
  });
});

describe("describeConfusion", () => {
  it("is the sentence the CLI prints", () => {
    expect(describeConfusion(cell("ticket2", "search_users", 7, 0.875))).toBe(
      "search_users captures 88% of the prompts meant for ticket2.",
    );
  });
});

describe("buildMatrix", () => {
  it("rows the expected tools and pushes the nothing column last", () => {
    const cells = [
      cell("a", "a", 3, 0.6),
      cell("a", "b", 2, 0.4),
      cell("b", "b", 4, 0.8),
      cell("b", null, 1, 0.2),
    ];
    const m = buildMatrix(cells);
    expect(m.rows).toEqual(["a", "b"]);
    expect(m.hasNothing).toBe(true);
    expect(m.cols[m.cols.length - 1]).toBe("(nothing)");
    expect(m.at("a", "b")?.count).toBe(2);
    expect(m.at("b", "(nothing)")?.share).toBe(0.2);
  });
});
