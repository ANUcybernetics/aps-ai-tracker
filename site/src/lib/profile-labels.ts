// Human labels for the closed vocabularies in profiles.py / changes.py, shared
// by the statement report card, the story list, the timeline and the policy
// page so a term reads the same everywhere.
import type { ChangeKind, Profile } from "@/types/exporter";
import { NOISE_KINDS } from "@/lib/schemas";

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

// The ladder every view groups by, from the two questions the classification
// answers: did the agency edit at all (noise = no), and did the substance
// change? "Substance" means exactly the substantive kind — a claim, commitment,
// fact or disclosure added, removed or altered. Expansion and restructure are
// revisions: new words, same substance; never counted as substance. An
// unclassified pair (nothing has read the diff yet) is shown fail-open but
// counted as nothing.
export type ChangeTier = "substance" | "revision" | "cosmetic" | "noise" | "unclassified" | "first";

export function changeTier(kind: ChangeKind): ChangeTier {
  if (kind === "first-seen") return "first";
  if (kind === "unclassified") return "unclassified";
  if (kind === "substantive") return "substance";
  if (kind === "expansion" || kind === "restructure") return "revision";
  if (NOISE_KINDS.has(kind)) return "noise";
  return "cosmetic"; // cosmetic, reordering
}

// What the feed shows by default and "the story so far" narrates: everything
// that changed (or may have changed) what a statement says.
export const READABLE_TIERS: ReadonlySet<ChangeTier> = new Set([
  "substance",
  "revision",
  "unclassified",
]);

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

// Where each question the profile asks comes from. Mirrors FIELD_SOURCES /
// FIELD_SOURCE in profiles.py; the report card and the reading page show it so
// the schema is never mistaken for the policy itself.
export type FieldSource = "standard" | "policy" | "ai-plan" | "tracker";

export const FIELD_SOURCE_LABEL: Record<
  FieldSource,
  { short: string; long: string; href: string | null }
> = {
  standard: {
    short: "Standard",
    long: "DTA Standard for AI transparency statements v2.0 (minimum content)",
    href: "https://www.digital.gov.au/ai/ai-in-government-policy/standard-ai-transparency-statements",
  },
  policy: {
    short: "Policy v2.0",
    long: "Policy for the responsible use of AI in government v2.0 (mandatory requirements)",
    href: "https://www.digital.gov.au/ai/ai-in-government-policy/strategy-and-oversight",
  },
  "ai-plan": {
    short: "AI Plan",
    long: "AI Plan for the Australian Public Service 2025 (Department of Finance)",
    href: "https://www.finance.gov.au/about-us/news/2025/establishing-chief-ai-officers-aps",
  },
  tracker: {
    short: "This tracker",
    long: "This tracker's own reading, not required by any instrument",
    href: null,
  },
};

// Every question the profile asks, grouped by source, for the reading page.
export const PROFILE_QUESTIONS: { source: FieldSource; label: string }[] = [
  { source: "standard", label: "Intentions behind AI use" },
  { source: "standard", label: "Usage patterns and domains in use (Attachment A classification)" },
  {
    source: "standard",
    label: "Whether the public interacts with or is affected by AI without human review",
  },
  { source: "standard", label: "Measures to monitor effectiveness and protect the public" },
  { source: "standard", label: "Compliance with the policy" },
  { source: "standard", label: "Compliance with legislation" },
  { source: "standard", label: "When the statement was last updated" },
  { source: "standard", label: "A public contact" },
  { source: "policy", label: "Review cadence (annually, or sooner on a significant change)" },
  { source: "policy", label: "Accountable official designated" },
  { source: "policy", label: "Strategic position on AI (due within 6 months of v2.0)" },
  { source: "policy", label: "Internal AI use-case register (due within 12 months)" },
  { source: "policy", label: "Mandatory staff training (due within 12 months)" },
  { source: "ai-plan", label: "Chief AI Officer (due July 2026)" },
  {
    source: "tracker",
    label: "An explicit commitment to a human intermediary for public-facing AI",
  },
  { source: "tracker", label: "Named safeguards, named tools, explicit commitments" },
  {
    source: "tracker",
    label: "Which policy version the statement refers to; a stated first-published date",
  },
];

// A stated date (YYYY-MM or YYYY-MM-DD) in the site's date style.
export function formatStatedDate(stated: string): string {
  const [y, m, d] = stated.split("-");
  const month = new Date(Number(y), Number(m) - 1, 1).toLocaleString("en-AU", { month: "short" });
  return d ? `${Number(d)} ${month} ${y}` : `${month} ${y}`;
}
