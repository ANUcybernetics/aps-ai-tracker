import type { AgencySize, CoverageStatus } from "@/types/exporter";

const DATE = new Intl.DateTimeFormat("en-AU", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

export function formatDate(iso: string): string {
  return DATE.format(new Date(iso));
}

export function originalityPercent(score: number): number {
  return Math.round(score * 100);
}

// Map a passage's reuse count to a 0–4 heat step (unique → ubiquitous). Template
// language that isn't verbatim-shared still reads as at least lightly shared.
export function heatLevel(sharedCount: number, canonical = false): number {
  const base =
    sharedCount < 2 ? 0 : sharedCount < 4 ? 1 : sharedCount < 10 ? 2 : sharedCount < 25 ? 3 : 4;
  return canonical ? Math.max(base, 2) : base;
}

export function signedDelta(n: number): string {
  return n > 0 ? `+${n}` : `${n}`;
}

export const SIZE_LABEL: Record<AgencySize, string> = {
  micro: "Micro",
  "extra-small": "Extra small",
  small: "Small",
  medium: "Medium",
  large: "Large",
  "extra-large": "Extra large",
  unknown: "Unknown",
};

export const STATUS_LABEL: Record<CoverageStatus, string> = {
  published: "Published",
  "not-yet": "Not yet published",
  exempt: "Exempt / out of scope",
};
