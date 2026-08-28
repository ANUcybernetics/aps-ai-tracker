import { describe, expect, it } from "vitest";
import { formatDate } from "./format";

describe("formatDate", () => {
  it("keeps the Canberra calendar day for an early-morning scrape event", () => {
    // 03:04 AEST is 17:04 UTC the previous day; the date shown must be the 28th
    // whatever zone the build runs in.
    expect(formatDate("2026-08-28T03:04:18+10:00")).toBe("28 Aug 2026");
  });

  it("honours daylight saving (AEDT) offsets", () => {
    expect(formatDate("2025-11-11T00:30:00+11:00")).toBe("11 Nov 2025");
  });

  it("renders a UTC timestamp on the Canberra day it falls on", () => {
    expect(formatDate("2026-08-27T17:04:18Z")).toBe("28 Aug 2026");
  });
});
