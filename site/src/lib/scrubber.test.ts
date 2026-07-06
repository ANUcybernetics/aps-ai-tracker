import { describe, expect, it } from "vitest";
import { MIN_GAP, buildScrubberDots, revAnchor, spreadOut, timePercent } from "./scrubber";
import type { TimelineRevision } from "@/types/exporter";

const START = "2025-11-11T00:00:00+11:00";
const END = "2026-07-06T00:00:00+11:00";

function rev(overrides: Partial<TimelineRevision>): TimelineRevision {
  return {
    sha: "0123456789abcdef",
    date: "2026-03-01T12:00:00+11:00",
    subject: "update",
    message: "update",
    kind: "updated",
    isNoise: false,
    chars: 1000,
    charDelta: 10,
    body: "body",
    ...overrides,
  };
}

describe("timePercent", () => {
  it("maps the axis endpoints to 0 and 100", () => {
    expect(timePercent(START, START, END)).toBe(0);
    expect(timePercent(END, START, END)).toBe(100);
  });

  it("places the midpoint near 50", () => {
    const mid = new Date((Date.parse(START) + Date.parse(END)) / 2).toISOString();
    expect(timePercent(mid, START, END)).toBeCloseTo(50, 5);
  });

  it("clamps dates outside the axis", () => {
    expect(timePercent("2020-01-01T00:00:00Z", START, END)).toBe(0);
    expect(timePercent("2030-01-01T00:00:00Z", START, END)).toBe(100);
  });

  it("degrades to 100 when the axis is empty or inverted", () => {
    expect(timePercent(START, START, START)).toBe(100);
    expect(timePercent(START, END, START)).toBe(100);
  });
});

describe("spreadOut", () => {
  it("leaves well-spaced values untouched", () => {
    expect(spreadOut([0, 50, 100])).toEqual([0, 50, 100]);
  });

  it("pushes colliding values apart to the minimum gap", () => {
    const out = spreadOut([50, 50, 50]);
    expect(out[1] - out[0]).toBeCloseTo(MIN_GAP, 5);
    expect(out[2] - out[1]).toBeCloseTo(MIN_GAP, 5);
  });

  it("preserves order for a dense daily cluster", () => {
    const out = spreadOut(Array.from({ length: 30 }, (_, i) => 40 + i * 0.1));
    for (let i = 1; i < out.length; i++) {
      expect(out[i] - out[i - 1]).toBeGreaterThanOrEqual(MIN_GAP - 1e-9);
    }
  });

  it("pulls a cluster at the end back inside the track", () => {
    const out = spreadOut([99, 99.5, 100]);
    expect(out[2]).toBe(100);
    expect(out[0]).toBeGreaterThanOrEqual(0);
    for (let i = 1; i < out.length; i++) {
      expect(out[i] - out[i - 1]).toBeGreaterThanOrEqual(MIN_GAP - 1e-9);
    }
  });

  it("handles empty and single-element input", () => {
    expect(spreadOut([])).toEqual([]);
    expect(spreadOut([42])).toEqual([42]);
  });

  it("keeps every dot on the track even when they cannot all fit at minGap", () => {
    const out = spreadOut(Array.from({ length: 200 }, () => 50));
    for (const p of out) {
      expect(p).toBeGreaterThanOrEqual(0);
      expect(p).toBeLessThanOrEqual(100);
    }
    for (let i = 1; i < out.length; i++) {
      expect(out[i]).toBeGreaterThanOrEqual(out[i - 1]);
    }
  });
});

describe("buildScrubberDots", () => {
  const timeline = [
    rev({ sha: "aaaa111aaaa", date: "2025-11-12T00:00:00+11:00", kind: "tracked-since" }),
    rev({ sha: "bbbb222bbbb", date: "2026-03-01T00:00:00+11:00", isNoise: true }),
    rev({ sha: "cccc333cccc", date: "2026-07-05T00:00:00+11:00", charDelta: -50 }),
  ];
  const dots = buildScrubberDots(timeline, START, END);

  it("produces one dot per revision, in timeline order", () => {
    expect(dots).toHaveLength(3);
    expect(dots.map((d) => d.shortSha)).toEqual(["aaaa111", "bbbb222", "cccc333"]);
  });

  it("marks only the newest revision as current, anchored to the statement", () => {
    expect(dots.map((d) => d.isCurrent)).toEqual([false, false, true]);
    expect(dots[2].anchor).toBe("statement");
  });

  it("anchors historical dots to their revision-history entries", () => {
    expect(dots[0].anchor).toBe(revAnchor("aaaa111aaaa"));
    expect(dots[0].anchor).toBe("rev-aaaa111");
  });

  it("carries noise and delta through to the dot", () => {
    expect(dots[1].isNoise).toBe(true);
    expect(dots[2].charDelta).toBe(-50);
  });

  it("flags dots near the track ends for tooltip clamping", () => {
    expect(dots[0].edge).toBe("start");
    expect(dots[1].edge).toBeNull();
    expect(dots[2].edge).toBe("end");
  });

  it("keeps dot positions monotonically increasing", () => {
    for (let i = 1; i < dots.length; i++) {
      expect(dots[i].pct).toBeGreaterThan(dots[i - 1].pct);
    }
  });
});
