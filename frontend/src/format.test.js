import { describe, expect, it } from "vitest";
import { comparison, todayAt, duration, noDifference } from "./format.js";

const stats = (safe, direct) => ({
  safe: { duration_min: 20, shaded_pct: null, risk_streets: null, reported_streets: 0, ...safe },
  direct: { duration_min: 14, shaded_pct: null, risk_streets: null, reported_streets: 0, ...direct },
});

describe("comparison", () => {
  it("summer shows extra time and shade", () => {
    expect(comparison(stats({ shaded_pct: 65 }, { shaded_pct: 20 }), "summer")).toBe(
      "6 min longer · 65% shaded vs 20%",
    );
  });

  it("monsoon counts avoided streets", () => {
    expect(comparison(stats({ risk_streets: 1 }, { risk_streets: 3 }), "monsoon")).toBe(
      "6 min longer · avoids 2 flood-risk streets",
    );
  });

  it("monsoon with no risk says so", () => {
    const s = stats({ risk_streets: 0, duration_min: 14 }, { risk_streets: 0 });
    expect(comparison(s, "monsoon")).toBe("No flood-risk streets on the way right now");
  });
});

describe("todayAt", () => {
  it("builds an IST timestamp", () => {
    expect(todayAt("16:00")).toMatch(/^\d{4}-\d{2}-\d{2}T16:00:00\+05:30$/);
  });
});

describe("reports", () => {
  it("monsoon counts avoided reported floods too", () => {
    const s = stats({ risk_streets: 0 }, { risk_streets: 1, reported_streets: 1 });
    expect(comparison(s, "monsoon")).toBe("6 min longer · avoids 2 flood-risk streets");
  });
});

it("duration switches to hours from 60 min", () => {
  expect(duration(45.4)).toBe("45 min");
  expect(duration(93)).toBe("1 h 33 min");
  expect(duration(120)).toBe("2 h 0 min");
});

describe("noDifference", () => {
  const s = (pct, min, risk = 0) => ({ shaded_pct: pct, duration_min: min, risk_streets: risk, reported_streets: 0 });
  it("is true only when shade and time match", () => {
    expect(noDifference({ safe: s(31, 13.2), direct: s(31, 12.8) }, "summer")).toBe(true);
    expect(noDifference({ safe: s(15, 93), direct: s(13, 93) }, "summer")).toBe(false);
    expect(noDifference({ safe: s(0, 20, 0), direct: s(0, 20, 3) }, "monsoon")).toBe(false);
  });
});
