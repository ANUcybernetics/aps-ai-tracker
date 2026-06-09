// Shapes of the JSON the Python `export` command writes into src/generated/.
// Keep in sync with src/aps_ai_transparency_tracker/export.py.

export type AgencySize =
  | "micro"
  | "extra-small"
  | "small"
  | "medium"
  | "large"
  | "extra-large"
  | "unknown";

export type CoverageStatus = "published" | "not-yet" | "exempt";
export type SourceType = "html" | "pdf";
export type EventKind = "published" | "tracked-since" | "updated";

export interface Meta {
  headSha: string;
  builtAt: string;
  firstCommit: string | null;
  corpusStart: string | null;
  apiUsed: boolean;
  counts: {
    agencies: number;
    published: number;
    notYet: number;
    exempt: number;
    statements: number;
    revisions: number;
    embedded: number;
  };
}

export interface AgencyRow {
  abbr: string;
  name: string;
  size: AgencySize;
  url: string | null;
  status: CoverageStatus;
  statementId: string | null;
  firstSeen: string | null;
  firstSeenIsBulkImport: boolean | null;
  lastUpdated: string | null;
  revisionCount: number;
  originality: number | null;
}

export interface AgencyIndex {
  agencies: AgencyRow[];
}

export interface TimelineRevision {
  sha: string;
  date: string;
  subject: string;
  message: string;
  kind: EventKind;
  isNoise: boolean;
  chars: number;
  charDelta: number;
  body: string;
}

export interface PassageRow {
  normKey: string;
  kind: "paragraph" | "list_item" | "heading";
  rawText: string;
  sharedCount: number;
  isBoilerplate: boolean;
  containsCanonicalPhrase: boolean;
}

export interface Originality {
  score: number;
  sharedChars: number;
  totalChars: number;
  unique: number;
  shared: number;
}

export interface Neighbour {
  abbr: string;
  score: number;
}

export interface StatementDoc {
  abbr: string;
  agency: string;
  title: string;
  sourceUrl: string | null;
  finalUrl?: string;
  sourceType: SourceType;
  body: string;
  frontmatter: Record<string, unknown>;
  timeline: TimelineRevision[];
  passages: PassageRow[];
  originality: Originality;
  neighbours: Neighbour[];
}

export interface TimelineEvent {
  id: string;
  sha: string;
  date: string;
  statementId: string;
  abbr: string;
  agency: string;
  size: AgencySize;
  summary: string;
  kind: EventKind;
  isNoise: boolean;
}

export interface TimelineData {
  events: TimelineEvent[];
}

// Temporal provenance for a shared passage: which tracked statement showed it
// earliest. "First observed by us", never proof of authorship — a passage may
// predate the corpus. `tier` grades how much the ordering bears (see export.py).
export interface FirstObserved {
  abbr: string | null; // earliest agency; null when several tie
  date: string; // ISO date the earliest member first showed the passage
  tier: "added" | "present-at-start" | "tied";
  order: { abbr: string; date: string }[]; // every member, oldest first
}

export interface PassageCluster {
  normKey: string;
  canonicalText: string;
  kind: "paragraph" | "list_item" | "heading" | "phrase";
  memberAbbrs: string[];
  count: number;
  alsoInDta: boolean;
  containsCanonicalPhrase: boolean;
  firstObserved: FirstObserved | null;
  mergeMethod: "exact" | "phrase";
}

export interface Propagation {
  clusters: PassageCluster[];
  originality: { abbr: string; score: number }[];
  ursource: string;
}

export interface Edge {
  a: string;
  b: string;
  score: number;
}

export interface Similarity {
  model: string;
  k: number;
  abbrs: string[];
  neighbours: Record<string, Neighbour[]>;
  edges: Edge[];
}

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
