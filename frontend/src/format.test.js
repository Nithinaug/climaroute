import { describe, expect, it } from "vitest";
import { comparison, conditionsText, todayAt, duration } from "./format.js";

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

describe("conditionsText", () => {
  it("summer shows weather and shade date", () => {
    const c = { temperature_c: 31.4, cloud_cover_pct: 20, heat_factor: 0.53, shade_date: "2026-10-08", active_reports: 1 };
    expect(conditionsText(c, "summer")).toBe(
      "31°C · 20% cloud · heat weight 0.53 · shade for 2026-10-08 · 1 flood report",
    );
  });
});

it("duration switches to hours from 60 min", () => {
  expect(duration(45.4)).toBe("45 min");
  expect(duration(93)).toBe("1 h 33 min");
  expect(duration(120)).toBe("2 h 0 min");
});
