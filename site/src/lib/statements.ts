// Per-statement documents, loaded at build time from the `statements` content
// collection (one JSON file per statement, glob-loaded — see
// src/content.config.ts). These carry full revision bodies, so import this
// module only from pages that render statement detail (the statement pages and
// the timeline's build-time diffs).
import { getCollection } from "astro:content";

import type { StatementDoc } from "@/types/exporter";

// All statements keyed by abbr, for lookups (e.g. joining a timeline event to
// its statement's revision history).
export async function getStatements(): Promise<Record<string, StatementDoc>> {
  const entries = await getCollection("statements");
  const byAbbr: Record<string, StatementDoc> = {};
  for (const entry of entries) byAbbr[entry.data.abbr] = entry.data;
  return byAbbr;
}

export async function getAllStatements(): Promise<StatementDoc[]> {
  const entries = await getCollection("statements");
  return entries.map((entry) => entry.data).toSorted((a, b) => a.abbr.localeCompare(b.abbr));
}
