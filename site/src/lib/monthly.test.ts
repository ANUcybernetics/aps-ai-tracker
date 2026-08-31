import { describe, expect, it } from "vitest";
import { monthKey, monthlyMix } from "./monthly";

describe("monthKey", () => {
  it("uses the Canberra calendar month, not the timestamp's own", () => {
    // 15:00 UTC on 31 Jul is 1 Aug in AEST, whatever zone the build runs in.
    expect(monthKey("2026-07-31T15:00:00Z")).toBe("2026-08");
    expect(monthKey("2026-08-28T03:04:18+10:00")).toBe("2026-08");
  });
});

describe("monthlyMix", () => {
  it("stacks tiers per month and zero-fills quiet months", () => {
    const rows = monthlyMix([
      { date: "2025-11-11T03:00:00+11:00", changeKind: "substantive" },
      { date: "2025-11-12T03:00:00+11:00", changeKind: "cosmetic" },
      { date: "2025-11-12T03:00:00+11:00", changeKind: "link-churn" },
      { date: "2026-01-05T03:00:00+11:00", changeKind: "expansion" },
    ]);
    expect(rows).toEqual([
      { month: "2025-11", substance: 1, cosmetic: 1, noise: 1 },
      { month: "2025-12", substance: 0, cosmetic: 0, noise: 0 },
      { month: "2026-01", substance: 1, cosmetic: 0, noise: 0 },
    ]);
  });

  it("keeps a first-seen-only month on the axis but out of the stacks", () => {
    const rows = monthlyMix([
      { date: "2025-11-11T03:00:00+11:00", changeKind: "first-seen" },
      { date: "2025-12-02T03:00:00+11:00", changeKind: "substantive" },
    ]);
    expect(rows).toEqual([
      { month: "2025-11", substance: 0, cosmetic: 0, noise: 0 },
      { month: "2025-12", substance: 1, cosmetic: 0, noise: 0 },
    ]);
  });

  it("returns nothing for no events", () => {
    expect(monthlyMix([])).toEqual([]);
  });
});
