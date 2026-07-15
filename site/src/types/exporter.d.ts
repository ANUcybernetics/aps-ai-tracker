// Shapes of the JSON the Python `export` command writes into src/generated/.
// The data types are inferred from the zod schemas in src/lib/schemas.ts (the
// single source of truth, validated at build time); this barrel re-exports them
// under their historical names so consumers keep importing from "@/types/exporter".
// Keep schemas in sync with src/aps_ai_tracker/export.py.

export type {
  AgencySize,
  CoverageStatus,
  SourceType,
  EventKind,
  Meta,
  AgencyRow,
  TimelineRevision,
  PassageRow,
  Originality,
  Neighbour,
  StatementDoc,
  TimelineEvent,
  FirstObserved,
  PassageCluster,
  Propagation,
  Edge,
  Similarity,
} from "@/lib/schemas";

import type { AgencySize, Edge } from "@/lib/schemas";

// Assembled by the /data/similarity.graph.json endpoint from the validated
// similarity + agency data, so these stay hand-written rather than
// schema-inferred.
export interface GraphNode {
  id: string;
  abbr: string;
  size: AgencySize;
  originality: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: Edge[];
}
