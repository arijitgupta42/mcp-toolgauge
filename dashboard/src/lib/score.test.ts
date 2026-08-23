import { describe, expect, it } from "vitest";
import { bandVar, scoreBand } from "./score";

/*
 * These pin the band ladder to mcp_doctor/health.py's `_BANDS` / `color_for`. If the Python
 * moves a boundary and this file is not moved with it, the dashboard would colour a score
 * differently from the badge on the same repo -- so the boundaries are asserted exactly, at
 * the floor and one below it, for every band.
 */
describe("scoreBand", () => {
  it("matches health.py at every boundary", () => {
    expect(scoreBand(100)).toBe("brightgreen");
    expect(scoreBand(90)).toBe("brightgreen");
    expect(scoreBand(89)).toBe("green");
    expect(scoreBand(75)).toBe("green");
    expect(scoreBand(74)).toBe("yellowgreen");
    expect(scoreBand(60)).toBe("yellowgreen");
    expect(scoreBand(59)).toBe("yellow");
    expect(scoreBand(45)).toBe("yellow");
    expect(scoreBand(44)).toBe("orange");
    expect(scoreBand(30)).toBe("orange");
    expect(scoreBand(29)).toBe("red");
    expect(scoreBand(0)).toBe("red");
  });

  it("puts the two fixture scores in the expected bands", () => {
    // goodserver 96 -> brightgreen, badserver 28 -> red. The whole demo in two numbers.
    expect(scoreBand(96)).toBe("brightgreen");
    expect(scoreBand(28)).toBe("red");
  });
});

describe("bandVar", () => {
  it("names the matching CSS custom property", () => {
    expect(bandVar(96)).toBe("var(--band-brightgreen)");
    expect(bandVar(28)).toBe("var(--band-red)");
  });
});
