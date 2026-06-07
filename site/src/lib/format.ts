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
