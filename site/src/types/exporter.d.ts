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
  ChangeKind,
  Meta,
  AgencyRow,
  TimelineRevision,
  PassageRow,
  Originality,
  Profile,
  ProfileDelta,
  Currency,
  Adoption,
  StatementDoc,
  TimelineEvent,
  FirstObserved,
  PassageCluster,
  Propagation,
} from "@/lib/schemas";
