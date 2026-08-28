// Human labels for the closed vocabularies in profiles.py / changes.py, shared
// by the statement report card, the story list, the timeline and the policy
// page so a term reads the same everywhere.
import type { ChangeKind, Profile } from "@/types/exporter";
import { CONTENT_KINDS, NOISE_KINDS } from "@/lib/schemas";

export const CHANGE_KIND_LABEL: Record<ChangeKind, string> = {
  "first-seen": "first tracked",
  formatting: "formatting only",
  "link-churn": "links only",
  chrome: "page chrome",
  "date-stamp": "date stamp",
  "scrape-noise": "scrape noise",
  reordering: "reordered",
  cosmetic: "cosmetic",
  expansion: "expanded",
  restructure: "restructured",
  substantive: "substantive",
  unclassified: "unclassified",
};

export type ChangeTier = "content" | "cosmetic" | "noise" | "first";

export function changeTier(kind: ChangeKind): ChangeTier {
  if (kind === "first-seen") return "first";
  if (NOISE_KINDS.has(kind)) return "noise";
  if (CONTENT_KINDS.has(kind)) return "content";
  // unclassified is treated as content: it could be anything, so show it
  return kind === "unclassified" ? "content" : "cosmetic";
}

export const USAGE_PATTERN_LABEL: Record<Profile["usage_patterns"][number], string> = {
  "decision-making-and-administrative-action": "Decision making and administrative action",
  "analytics-for-insights": "Analytics for insights",
  "workplace-productivity": "Workplace productivity",
  "image-processing": "Image processing",
};

export const DOMAIN_LABEL: Record<Profile["domains"][number], string> = {
  "service-delivery": "Service delivery",
  "compliance-and-fraud-detection": "Compliance and fraud detection",
  "law-enforcement-intelligence-and-security": "Law enforcement, intelligence and security",
  "policy-and-legal": "Policy and legal",
  scientific: "Scientific",
  "corporate-and-enabling": "Corporate and enabling",
};

export const MEASURE_LABEL: Record<Profile["measures"][number], string> = {
  "risk-assessment": "risk assessment",
  "human-review-of-outputs": "human review of outputs",
  "audit-or-assurance": "audit or assurance",
  "staff-training": "staff training",
  "use-case-register": "use-case register",
  "incident-or-concern-reporting": "incident or concern reporting",
  "testing-or-evaluation": "testing or evaluation",
  "privacy-or-security-controls": "privacy or security controls",
  "governance-body": "a governance body",
  "acceptable-use-policy": "an acceptable-use policy",
};

export const PRESENCE_LABEL: Record<Profile["chief_ai_officer"], string> = {
  "not-mentioned": "not mentioned",
  planned: "planned",
  "in-place": "in place",
};

export const TRAINING_LABEL: Record<Profile["staff_training"], string> = {
  "not-mentioned": "not mentioned",
  available: "available",
  mandatory: "mandatory",
};

export const PUBLIC_FACING_LABEL: Record<Profile["public_facing"], string> = {
  "not-addressed": "not addressed",
  none: "none",
  "with-human-review": "yes, with human review",
  "without-human-review": "yes, without human review",
  unclear: "unclear",
};

export const REVIEW_LABEL: Record<Profile["review_cadence"], string> = {
  "not-stated": "not stated",
  annual: "annually",
  "on-change": "when the approach changes",
  "annual-and-on-change": "annually and when the approach changes",
  other: "other",
};

export const POLICY_VERSION_LABEL: Record<Profile["policy_version"], string> = {
  "not-referenced": "not referenced",
  v1: "version 1",
  v2: "version 2.0",
  unspecified: "unspecified version",
};

export const COMMITMENT_KIND_LABEL: Record<Profile["commitments"][number]["kind"], string> = {
  "will-not": "will not",
  will: "will",
  "human-oversight": "human oversight",
};

// The Standard's minimum elements, in the order the report card shows them.
// Keys match profiles.py STANDARD_ELEMENTS.
export const STANDARD_ELEMENTS: { key: string; label: string }[] = [
  { key: "intentions", label: "Intentions behind AI use" },
  { key: "classification", label: "Use classified by DTA usage pattern or domain" },
  { key: "public-facing", label: "Public-facing use addressed" },
  { key: "monitoring", label: "Monitoring and protection measures" },
  { key: "policy-compliance", label: "Compliance with the policy" },
  { key: "legislation", label: "Compliance with legislation" },
  { key: "last-updated", label: "Date last updated" },
  { key: "contact", label: "Public contact" },
];

// A stated date (YYYY-MM or YYYY-MM-DD) in the site's date style.
export function formatStatedDate(stated: string): string {
  const [y, m, d] = stated.split("-");
  const month = new Date(Number(y), Number(m) - 1, 1).toLocaleString("en-AU", { month: "short" });
  return d ? `${Number(d)} ${month} ${y}` : `${month} ${y}`;
}
