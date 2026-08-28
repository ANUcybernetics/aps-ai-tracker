// Zod schemas for the JSON the Python `export` command writes into
// src/generated/. These are the single source of truth for both the Astro
// content collections (see src/content.config.ts) and the TypeScript types the
// rest of the site consumes (re-exported from src/types/exporter.d.ts). Validated
// at build time, so a drift between this file and export.py fails the build
// loudly rather than surfacing as `undefined` deep inside a component.
//
// Keep in sync with src/aps_ai_tracker/export.py.
import { z } from "astro/zod";

export const agencySizeSchema = z.enum([
  "micro",
  "extra-small",
  "small",
  "medium",
  "large",
  "extra-large",
  "unknown",
]);

export const coverageStatusSchema = z.enum(["published", "not-yet", "exempt"]);
// What the AI policy asks of the body, independent of whether it has published:
// mandatory for non-corporate Commonwealth entities, voluntary for corporate
// entities, exempt for the defence portfolio and national intelligence community.
export const agencyScopeSchema = z.enum(["mandatory", "voluntary", "exempt"]);
export const sourceTypeSchema = z.enum(["html", "pdf"]);
export const eventKindSchema = z.enum(["added", "tracked-since", "updated"]);

// Content-based classification of what a revision changed (see changes.py).
// Noise kinds mean nothing the agency wrote changed; cosmetic kinds are edits
// with no change of substance; content kinds are the ones worth reading.
export const changeKindSchema = z.enum([
  "first-seen",
  // noise
  "formatting",
  "link-churn",
  "chrome",
  "date-stamp",
  "scrape-noise",
  // cosmetic
  "reordering",
  "cosmetic",
  // content
  "expansion",
  "restructure",
  "substantive",
  // no rule matched, no cache entry and no model available
  "unclassified",
]);
export const changeMethodSchema = z.enum(["rule", "llm", "uncached"]);

export const NOISE_KINDS: ReadonlySet<ChangeKind> = new Set([
  "formatting",
  "link-churn",
  "chrome",
  "date-stamp",
  "scrape-noise",
]);
export const CONTENT_KINDS: ReadonlySet<ChangeKind> = new Set([
  "expansion",
  "restructure",
  "substantive",
]);

const changeFields = {
  changeKind: changeKindSchema,
  changeMethod: changeMethodSchema,
  model: z.string().nullable(), // which Claude model read the diff, when one did
  summary: z.string().nullable(), // plain-English one-liner, model-written
  noteworthy: z.array(z.string()), // substantive additions/removals, removals first
};

export const originalitySchema = z.object({
  score: z.number(),
  sharedChars: z.number(),
  totalChars: z.number(),
  unique: z.number(),
  shared: z.number(),
});

export const metaSchema = z.object({
  headSha: z.string(),
  builtAt: z.string(),
  firstCommit: z.string().nullable(),
  corpusStart: z.string().nullable(),
  counts: z.object({
    agencies: z.number(),
    published: z.number(),
    notYet: z.number(),
    exempt: z.number(),
    statements: z.number(),
    revisions: z.number(), // every capture that differed from the last
    changes: z.number(), // only the revisions whose substance changed
    profiled: z.number(),
  }),
});

// What a statement says about its own currency, against the policy's rules
// (see adoption.py). Stated dates are the agency's own; observed ones are ours.
// `updatedSincePolicyV2` is null when we cannot tell: the statement was first
// tracked after v2.0 took effect and gives no date of its own.
export const currencySchema = z.object({
  statedLastUpdated: z.string().nullable(),
  statedFirstPublished: z.string().nullable(),
  lastContentChange: z.string().nullable(),
  firstSeen: z.string(),
  updatedSincePolicyV2: z.boolean().nullable(),
  annualReviewOverdue: z.boolean().nullable(),
  evaluatedAt: z.string(), // the build date the verdicts were computed against
});

export const agencyRowSchema = z.object({
  abbr: z.string(),
  name: z.string(),
  size: agencySizeSchema,
  scope: agencyScopeSchema,
  // Portfolio per the Administrative Arrangements Order; null when not recorded.
  portfolio: z.string().nullable(),
  url: z.string().nullable(),
  status: coverageStatusSchema,
  statementId: z.string().nullable(),
  firstSeen: z.string().nullable(),
  lastUpdated: z.string().nullable(),
  revisionCount: z.number(), // captures that differed
  changeCount: z.number(), // changes of substance
  originality: z.number().nullable(),
  currency: currencySchema.nullable(),
});

// A statement's profile: what it claims, in the closed vocabularies of
// profiles.py (mirrors the pydantic `Profile`). Roles only, never names.
export const usagePatternSchema = z.enum([
  "decision-making-and-administrative-action",
  "analytics-for-insights",
  "workplace-productivity",
  "image-processing",
]);
export const domainSchema = z.enum([
  "service-delivery",
  "compliance-and-fraud-detection",
  "law-enforcement-intelligence-and-security",
  "policy-and-legal",
  "scientific",
  "corporate-and-enabling",
]);
export const presenceSchema = z.enum(["not-mentioned", "planned", "in-place"]);
export const measureSchema = z.enum([
  "risk-assessment",
  "human-review-of-outputs",
  "audit-or-assurance",
  "staff-training",
  "use-case-register",
  "incident-or-concern-reporting",
  "testing-or-evaluation",
  "privacy-or-security-controls",
  "governance-body",
  "acceptable-use-policy",
]);
export const commitmentSchema = z.object({
  text: z.string(),
  kind: z.enum(["will-not", "will", "human-oversight"]),
});
export const profileSchema = z.object({
  summary: z.string(),
  intentions_stated: z.boolean(),
  usage_patterns: z.array(usagePatternSchema),
  domains: z.array(domainSchema),
  public_facing: z.enum([
    "not-addressed",
    "none",
    "with-human-review",
    "without-human-review",
    "unclear",
  ]),
  public_interaction_commitment: z.boolean(),
  monitoring_measures_stated: z.boolean(),
  measures: z.array(measureSchema),
  accountable_official: z.enum(["not-mentioned", "designated"]),
  accountable_official_role: z.string().nullable(),
  chief_ai_officer: presenceSchema,
  chief_ai_officer_role: z.string().nullable(),
  use_case_register: presenceSchema,
  staff_training: z.enum(["not-mentioned", "available", "mandatory"]),
  strategic_position: presenceSchema,
  review_cadence: z.enum(["not-stated", "annual", "on-change", "annual-and-on-change", "other"]),
  first_published_stated: z.string().nullable(),
  last_updated_stated: z.string().nullable(),
  contact_provided: z.boolean(),
  named_tools: z.array(z.string()),
  policy_version: z.enum(["not-referenced", "v1", "v2", "unspecified"]),
  policy_compliance_stated: z.boolean(),
  legislation_compliance_stated: z.boolean(),
  commitments: z.array(commitmentSchema),
});

// One field-level change between two consecutive profiles.
export const profileDeltaSchema = z.object({
  field: z.string(),
  label: z.string(),
  direction: z.enum(["added", "removed", "changed"]),
  significance: z.enum(["minor", "notable", "significant"]),
  before: z.string().nullable(),
  after: z.string().nullable(),
});

export const timelineRevisionSchema = z.object({
  sha: z.string(),
  date: z.string(),
  subject: z.string(),
  message: z.string(),
  kind: eventKindSchema,
  ...changeFields,
  profileDeltas: z.array(profileDeltaSchema),
  isNoise: z.boolean(),
  chars: z.number(),
  charDelta: z.number(),
  body: z.string(),
});

export const passageRowSchema = z.object({
  normKey: z.string(),
  kind: z.enum(["paragraph", "list_item", "heading"]),
  rawText: z.string(),
  sharedCount: z.number(),
  isBoilerplate: z.boolean(),
  containsCanonicalPhrase: z.boolean(),
});

export const statementSchema = z.object({
  abbr: z.string(),
  agency: z.string(),
  title: z.string(),
  sourceUrl: z.string().nullable(),
  finalUrl: z.string().optional(),
  sourceType: sourceTypeSchema,
  body: z.string(),
  frontmatter: z.record(z.string(), z.unknown()),
  timeline: z.array(timelineRevisionSchema),
  passages: z.array(passageRowSchema),
  originality: originalitySchema,
  profile: profileSchema.nullable(),
  profileModel: z.string().nullable(), // which Claude model read the current profile
  // Which of the Standard's minimum elements the profile shows as present.
  standard: z.record(z.string(), z.boolean()).nullable(),
  currency: currencySchema,
  // The newest capture failed and was quarantined; `body` is the last good one.
  latestCaptureSuspect: z.boolean(),
});

export const timelineEventSchema = z.object({
  id: z.string(),
  sha: z.string(),
  date: z.string(),
  statementId: z.string(),
  abbr: z.string(),
  agency: z.string(),
  size: agencySizeSchema,
  commitSubject: z.string(),
  kind: eventKindSchema,
  ...changeFields,
  isNoise: z.boolean(),
});

// Temporal provenance for a shared passage: which tracked statement showed it
// earliest. "First observed by us", never proof of authorship — a passage may
// predate the corpus. `tier` grades how much the ordering bears (see export.py).
export const firstObservedSchema = z.object({
  abbr: z.string().nullable(), // earliest agency; null when several tie
  date: z.string(), // ISO date the earliest member first showed the passage
  tier: z.enum(["added", "present-at-start", "tied"]),
  order: z.array(z.object({ abbr: z.string(), date: z.string() })), // every member, oldest first
});

export const passageClusterSchema = z.object({
  normKey: z.string(),
  canonicalText: z.string(),
  kind: z.enum(["paragraph", "list_item", "heading", "phrase"]),
  memberAbbrs: z.array(z.string()),
  count: z.number(),
  alsoInDta: z.boolean(),
  containsCanonicalPhrase: z.boolean(),
  firstObserved: firstObservedSchema.nullable(),
  mergeMethod: z.enum(["exact", "phrase"]),
});

export const propagationSchema = z.object({
  clusters: z.array(passageClusterSchema),
  originality: z.array(z.object({ abbr: z.string(), score: z.number() })),
  ursource: z.string(),
});

// Monthly adoption of policy concepts across the corpus, plus every agency-level
// transition, from adoption.py.
export const adoptionSchema = z.object({
  months: z.array(z.string()),
  tracked: z.array(z.number()),
  concepts: z.array(z.object({ id: z.string(), label: z.string(), counts: z.array(z.number()) })),
  transitions: z.array(
    z.object({
      concept: z.string(),
      abbr: z.string(),
      date: z.string(),
      sha: z.string(),
      direction: z.enum(["added", "removed"]),
    }),
  ),
  milestones: z.array(z.object({ date: z.string(), label: z.string() })),
});

export type AgencySize = z.infer<typeof agencySizeSchema>;
export type CoverageStatus = z.infer<typeof coverageStatusSchema>;
export type SourceType = z.infer<typeof sourceTypeSchema>;
export type EventKind = z.infer<typeof eventKindSchema>;
export type ChangeKind = z.infer<typeof changeKindSchema>;
export type Originality = z.infer<typeof originalitySchema>;
export type Meta = z.infer<typeof metaSchema>;
export type AgencyRow = z.infer<typeof agencyRowSchema>;
export type TimelineRevision = z.infer<typeof timelineRevisionSchema>;
export type PassageRow = z.infer<typeof passageRowSchema>;
export type StatementDoc = z.infer<typeof statementSchema>;
export type TimelineEvent = z.infer<typeof timelineEventSchema>;
export type FirstObserved = z.infer<typeof firstObservedSchema>;
export type PassageCluster = z.infer<typeof passageClusterSchema>;
export type Propagation = z.infer<typeof propagationSchema>;
export type Profile = z.infer<typeof profileSchema>;
export type ProfileDelta = z.infer<typeof profileDeltaSchema>;
export type Currency = z.infer<typeof currencySchema>;
export type Adoption = z.infer<typeof adoptionSchema>;
