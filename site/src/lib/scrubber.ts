// Geometry and view-model for the revision scrubber on statement pages: a
// time-proportional track from the corpus start to the build date, with one
// dot per revision. Pure functions so the placement rules (clamping, collision
// nudging, tooltip edge handling) are unit-testable without a DOM.
import type { EventKind, TimelineRevision } from "@/types/exporter";

export interface ScrubberDot {
  shortSha: string;
  // Fragment the dot links to: the matching revision-history entry, or the
  // statement article itself for the current revision (the no-JS fallback).
  anchor: string;
  pct: number;
  date: string;
  kind: EventKind;
  isNoise: boolean;
  isCurrent: boolean;
  charDelta: number;
  // Dots near the track ends get their tooltip pinned to that edge so it
  // doesn't overflow the container.
  edge: "start" | "end" | null;
}

// Anchor id shared by the scrubber dots and the revision-history list items.
export function revAnchor(sha: string): string {
  return `rev-${sha.slice(0, 7)}`;
}

// Where a date falls on the axis, as a 0–100 percentage, clamped so dates
// outside the axis (e.g. a statement tracked before the corpus start) still
// render on the track.
export function timePercent(date: string, axisStart: string, axisEnd: string): number {
  const t = Date.parse(date);
  const a = Date.parse(axisStart);
  const b = Date.parse(axisEnd);
  if (!(b > a)) return 100;
  return Math.min(100, Math.max(0, ((t - a) / (b - a)) * 100));
}

// Minimum spacing between dot centres, in track percent — roughly one dot
// width, so daily-churn clusters stay individually hoverable.
export const MIN_GAP = 0.9;

// Spread an ascending list of percentages so consecutive values sit at least
// `minGap` apart, preserving order and staying within [0, 100]. A forward pass
// pushes collisions right; if that overflows the end, a backward pass pulls
// the tail back. Distorts time slightly for dense clusters, but keeps every
// revision clickable.
export function spreadOut(pcts: number[], minGap = MIN_GAP): number[] {
  const out = [...pcts];
  for (let i = 1; i < out.length; i++) {
    out[i] = Math.max(out[i], out[i - 1] + minGap);
  }
  if (out.length && out[out.length - 1] > 100) {
    out[out.length - 1] = 100;
    for (let i = out.length - 2; i >= 0; i--) {
      out[i] = Math.min(out[i], out[i + 1] - minGap);
    }
  }
  return out;
}

const EDGE_ZONE = 6;

export function buildScrubberDots(
  timeline: TimelineRevision[],
  axisStart: string,
  axisEnd: string,
): ScrubberDot[] {
  const pcts = spreadOut(timeline.map((rev) => timePercent(rev.date, axisStart, axisEnd)));
  return timeline.map((rev, i) => {
    const isCurrent = i === timeline.length - 1;
    const pct = pcts[i];
    return {
      shortSha: rev.sha.slice(0, 7),
      anchor: isCurrent ? "statement" : revAnchor(rev.sha),
      pct,
      date: rev.date,
      kind: rev.kind,
      isNoise: rev.isNoise,
      isCurrent,
      charDelta: rev.charDelta,
      edge: pct < EDGE_ZONE ? "start" : pct > 100 - EDGE_ZONE ? "end" : null,
    };
  });
}
