// Human labels for the closed vocabularies in profiles.py / changes.py, shared
// by the statement report card, the story list, the timeline and the policy
// page so a term reads the same everywhere.
import type { ChangeKind, Profile } from "@/types/exporter";
import { NOISE_KINDS } from "@/lib/schemas";

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

// The one label each tier wears wherever a change is shown. The finer kinds
// (links only, page chrome, expanded, restructured, ...) stay in the data
// downloads for anyone auditing the classification.
export const TIER_LABEL: Record<ChangeTier, string> = {
  substance: "substantive",
  revision: "reworded",
  cosmetic: "cosmetic",
  noise: "noise",
  unclassified: "not yet read",
  first: "first tracked",
};

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

// Every question a profile answers, in the order the instruments set them: the
// Standard's eight minimum elements (keys match profiles.py STANDARD_ELEMENTS),
// the policy's mandatory requirements, the AI Plan's Chief AI Officer, then the
// tracker's own questions. `fields` are the profile fields that answer each
// one (mirroring FIELD_SOURCE in profiles.py), so a change to a field is filed
// under the requirement it answers.
export type Requirement = {
  key: string;
  source: FieldSource;
  label: string;
  question: string;
  fields: string[];
};

export const REQUIREMENTS: Requirement[] = [
  {
    key: "intentions",
    source: "standard",
    label: "Intentions behind AI use",
    question: "Intentions behind AI use",
    fields: ["intentions_stated"],
  },
  {
    key: "classification",
    source: "standard",
    label: "Use classified by DTA usage pattern or domain",
    question: "Usage patterns and domains in use (Attachment A classification)",
    fields: ["usage_patterns", "domains"],
  },
  {
    key: "public-facing",
    source: "standard",
    label: "Public-facing use addressed",
    question: "Whether the public interacts with or is affected by AI without human review",
    fields: ["public_facing"],
  },
  {
    key: "monitoring",
    source: "standard",
    label: "Monitoring and protection measures",
    question: "Measures to monitor effectiveness and protect the public",
    fields: ["monitoring_measures_stated"],
  },
  {
    key: "policy-compliance",
    source: "standard",
    label: "Compliance with the policy",
    question: "Compliance with the policy",
    fields: ["policy_compliance_stated"],
  },
  {
    key: "legislation",
    source: "standard",
    label: "Compliance with legislation",
    question: "Compliance with legislation",
    fields: ["legislation_compliance_stated"],
  },
  {
    key: "last-updated",
    source: "standard",
    label: "Date last updated",
    question: "When the statement was last updated",
    fields: ["last_updated_stated"],
  },
  {
    key: "contact",
    source: "standard",
    label: "Public contact",
    question: "A public contact",
    fields: ["contact_provided"],
  },
  {
    key: "review",
    source: "policy",
    label: "Review cadence",
    question: "Review cadence (annually, or sooner on a significant change)",
    fields: ["review_cadence"],
  },
  {
    key: "accountable-official",
    source: "policy",
    label: "Accountable official",
    question: "Accountable official designated",
    fields: ["accountable_official"],
  },
  {
    key: "strategic-position",
    source: "policy",
    label: "Strategic position on AI",
    question: "Strategic position on AI (due within 6 months of v2.0)",
    fields: ["strategic_position"],
  },
  {
    key: "use-case-register",
    source: "policy",
    label: "AI use-case register",
    question: "Internal AI use-case register (due within 12 months)",
    fields: ["use_case_register"],
  },
  {
    key: "training",
    source: "policy",
    label: "Staff training",
    question: "Mandatory staff training (due within 12 months)",
    fields: ["staff_training"],
  },
  {
    key: "chief-ai-officer",
    source: "ai-plan",
    label: "Chief AI Officer",
    question: "Chief AI Officer (due July 2026)",
    fields: ["chief_ai_officer"],
  },
  {
    key: "human-intermediary",
    source: "tracker",
    label: "Human intermediary for public-facing AI",
    question: "An explicit commitment to a human intermediary for public-facing AI",
    fields: ["public_interaction_commitment"],
  },
  {
    key: "commitments",
    source: "tracker",
    label: "Commitments",
    question:
      "Explicit commitments: what the agency will do, will not do, or keep under human oversight",
    fields: ["commitments"],
  },
  {
    key: "safeguards",
    source: "tracker",
    label: "Named safeguards",
    question: "Named safeguards (risk assessment, audit, testing and so on)",
    fields: ["measures"],
  },
  {
    key: "named-tools",
    source: "tracker",
    label: "Named tools",
    question: "Named AI tools",
    fields: ["named_tools"],
  },
  {
    key: "policy-version",
    source: "tracker",
    label: "Policy version referenced",
    question: "Which policy version the statement refers to",
    fields: ["policy_version"],
  },
  {
    key: "first-published",
    source: "tracker",
    label: "Stated first-published date",
    question: "A stated first-published date",
    fields: ["first_published_stated"],
  },
];

export const STANDARD_ELEMENTS = REQUIREMENTS.filter((r) => r.source === "standard");

const REQUIREMENT_BY_FIELD = new Map(REQUIREMENTS.flatMap((r) => r.fields.map((f) => [f, r])));

// The requirement a profile field answers, for filing a change under it.
export function requirementFor(field: string): Requirement | undefined {
  return REQUIREMENT_BY_FIELD.get(field);
}

// A stated date (YYYY-MM or YYYY-MM-DD) in the site's date style.
export function formatStatedDate(stated: string): string {
  const [y, m, d] = stated.split("-");
  const month = new Date(Number(y), Number(m) - 1, 1).toLocaleString("en-AU", { month: "short" });
  return d ? `${Number(d)} ${month} ${y}` : `${month} ${y}`;
}
