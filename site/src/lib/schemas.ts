// Zod schemas for the JSON the Python `export` command writes into
// src/generated/. These are the single source of truth for both the Astro
// content collections (see src/content.config.ts) and the TypeScript types the
// rest of the site consumes (re-exported from src/types/exporter.d.ts). Validated
// at build time, so a drift between this file and export.py fails the build
// loudly rather than surfacing as `undefined` deep inside a component.
//
// Keep in sync with src/aps_ai_transparency_tracker/export.py.
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
export const sourceTypeSchema = z.enum(["html", "pdf"]);
export const eventKindSchema = z.enum(["added", "tracked-since", "updated"]);

export const neighbourSchema = z.object({
  abbr: z.string(),
  score: z.number(),
});

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
  apiUsed: z.boolean(),
  counts: z.object({
    agencies: z.number(),
    published: z.number(),
    notYet: z.number(),
    exempt: z.number(),
    statements: z.number(),
    revisions: z.number(),
    embedded: z.number(),
  }),
});

export const agencyRowSchema = z.object({
  abbr: z.string(),
  name: z.string(),
  size: agencySizeSchema,
  url: z.string().nullable(),
  status: coverageStatusSchema,
  statementId: z.string().nullable(),
  firstSeen: z.string().nullable(),
  firstSeenIsBulkImport: z.boolean().nullable(),
  lastUpdated: z.string().nullable(),
  revisionCount: z.number(),
  originality: z.number().nullable(),
});

export const timelineRevisionSchema = z.object({
  sha: z.string(),
  date: z.string(),
  subject: z.string(),
  message: z.string(),
  kind: eventKindSchema,
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
  neighbours: z.array(neighbourSchema),
});

export const timelineEventSchema = z.object({
  id: z.string(),
  sha: z.string(),
  date: z.string(),
  statementId: z.string(),
  abbr: z.string(),
  agency: z.string(),
  size: agencySizeSchema,
  summary: z.string(),
  kind: eventKindSchema,
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

export const edgeSchema = z.object({
  a: z.string(),
  b: z.string(),
  score: z.number(),
});

export const similaritySchema = z.object({
  model: z.string(),
  k: z.number(),
  abbrs: z.array(z.string()),
  neighbours: z.record(z.string(), z.array(neighbourSchema)),
  edges: z.array(edgeSchema),
});

export type AgencySize = z.infer<typeof agencySizeSchema>;
export type CoverageStatus = z.infer<typeof coverageStatusSchema>;
export type SourceType = z.infer<typeof sourceTypeSchema>;
export type EventKind = z.infer<typeof eventKindSchema>;
export type Neighbour = z.infer<typeof neighbourSchema>;
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
export type Edge = z.infer<typeof edgeSchema>;
export type Similarity = z.infer<typeof similaritySchema>;
