import { expect, it } from "vitest";
import { nightness, sunElevation } from "./nightMap.js";

it("follows the sun over Bengaluru", () => {
  const at = (iso) => sunElevation(new Date(iso), 12.97, 77.59);
  expect(at("2026-10-09T12:15:00+05:30")).toBeGreaterThan(70); // near overhead at noon
  expect(at("2026-10-09T00:15:00+05:30")).toBeLessThan(-60);
  expect(Math.abs(at("2026-10-09T18:05:00+05:30"))).toBeLessThan(3); // sunset ~18:05
  expect(nightness(30)).toBe(0);
  expect(nightness(0)).toBe(0.5);
  expect(nightness(-20)).toBe(1);
});
