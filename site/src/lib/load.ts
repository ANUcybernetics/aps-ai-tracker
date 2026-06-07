// Build-time loaders for the small, shared generated artifacts. Heavy per-
// statement docs (which carry full revision bodies) live in statements.ts so
// pages that only need index data don't pull them in.
import type {
  AgencyIndex,
  Meta,
  Propagation,
  Similarity,
  TimelineData,
} from "@/types/exporter";

import agenciesJson from "../generated/agencies.json";
import metaJson from "../generated/meta.json";
import propagationJson from "../generated/propagation.json";
import similarityJson from "../generated/similarity.json";
import timelineJson from "../generated/timeline.json";

export const meta = metaJson as unknown as Meta;
export const agencies = (agenciesJson as unknown as AgencyIndex).agencies;
export const timeline = (timelineJson as unknown as TimelineData).events;
export const propagation = propagationJson as unknown as Propagation;
export const similarity = similarityJson as unknown as Similarity;

export const publishedAgencies = agencies.filter((a) => a.status === "published");
