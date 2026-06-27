// Build-time loaders for the shared generated artifacts.
//
// The collection-shaped data (agencies, timeline, and per-statement docs) lives
// in content collections — see src/content.config.ts — and is read here through
// async accessors. The singletons (meta, propagation, similarity) are single
// JSON objects rather than entry sets, so they're imported directly and checked
// against their zod schema at module load; a drift from export.py fails the
// build instead of surfacing as undefined inside a component.
import { getCollection } from "astro:content";

import { metaSchema, propagationSchema, similaritySchema } from "@/lib/schemas";

import metaJson from "../generated/meta.json";
import propagationJson from "../generated/propagation.json";
import similarityJson from "../generated/similarity.json";

export const meta = metaSchema.parse(metaJson);
export const propagation = propagationSchema.parse(propagationJson);
export const similarity = similaritySchema.parse(similarityJson);

export async function getAgencies() {
  return (await getCollection("agencies")).map((entry) => entry.data);
}

export async function getTimeline() {
  return (await getCollection("timeline")).map((entry) => entry.data);
}
