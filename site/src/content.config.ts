import { defineCollection } from "astro:content";
import { file, glob } from "astro/loaders";

import { agencyRowSchema, statementSchema, timelineEventSchema } from "@/lib/schemas";

// The collection-shaped generated data (a set of entries each). The singleton
// artifacts — meta, propagation, similarity — are single JSON objects, not
// entry sets, so they stay a thin zod-validated load in src/lib/load.ts rather
// than being forced into a one-entry collection.

// One file per statement, id taken from the filename (e.g. AASB.json → "AASB",
// which equals the statement's own abbr).
const statements = defineCollection({
  loader: glob({ pattern: "*.json", base: "./src/generated/statements" }),
  schema: statementSchema,
});

// agencies.json wraps the rows under an `agencies` key; the file loader needs a
// top-level array with an `id` per entry, so unwrap and key each by its abbr.
const agencies = defineCollection({
  loader: file("src/generated/agencies.json", {
    parser: (text) =>
      (JSON.parse(text).agencies as { abbr: string }[]).map((a) => ({ id: a.abbr, ...a })),
  }),
  schema: agencyRowSchema,
});

// timeline.json wraps events under `events`; each already carries a unique `id`.
// NOTE: the file loader does NOT preserve array order — getCollection returns
// entries ordered by `id` (`abbr:sha`), i.e. grouped by agency, not the
// exporter's newest-first order. getTimeline() in src/lib/load.ts re-sorts by
// (date, id) desc to restore it; don't rely on the array order here.
const timeline = defineCollection({
  loader: file("src/generated/timeline.json", {
    parser: (text) => JSON.parse(text).events,
  }),
  schema: timelineEventSchema,
});

export const collections = { statements, agencies, timeline };
