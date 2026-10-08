import { describe, expect, it } from "vitest";
import { comparison, todayAt } from "./format.js";

const stats = (safe, direct) => ({
  safe: { duration_min: 20, shaded_pct: null, risk_streets: null, ...safe },
  direct: { duration_min: 14, shaded_pct: null, risk_streets: null, ...direct },
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
