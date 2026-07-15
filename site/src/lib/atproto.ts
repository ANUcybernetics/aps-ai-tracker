// The tracker's atproto identity and record model, shared by the Astro pages
// (AT-URI <link> tags) and the publish scripts under site/scripts/. Everything
// here is pure and env-free so it runs identically under Astro, vitest and tsx.
//
// Identifier scheme (see the me.benswift.transparencyStatement* lexicons in
// lexicons/ at the repo root): rkeys are deterministic — computable from the
// public corpus, never stored — so AT-URIs survive the loss of any state file.
//   site.standard.document/{abbr}                       current statement text
//   me.benswift.transparencyStatement/{abbr}            tracked-statement metadata
//   me.benswift.transparencyStatementRevision/{abbr}-{compact UTC observedAt}
//
// The handle (apsaitracker.bsky.social) is cosmetic and swappable; the DID is
// the durable identity every AT-URI hangs off.

export const TRACKER_DID = "did:plc:yhnshyrc2iev6z65u3uraon4";
export const TRACKER_HANDLE = "apsaitracker.bsky.social";
export const ATPROTO_SERVICE = "https://bsky.social";

export const SITE_URL = "https://anucybernetics.github.io/aps-ai-tracker/";
export const BASE_PATH = "/aps-ai-tracker";

export const PUBLICATION_COLLECTION = "site.standard.publication";
export const DOCUMENT_COLLECTION = "site.standard.document";
export const STATEMENT_COLLECTION = "me.benswift.transparencyStatement";
export const REVISION_COLLECTION = "me.benswift.transparencyStatementRevision";

export const PUBLICATION_URI = `at://${TRACKER_DID}/${PUBLICATION_COLLECTION}/self`;

/** "2025-11-11T17:12:58+11:00" -> "20251111T061258Z" (always UTC). */
export function compactUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) throw new Error(`unparseable datetime: ${iso}`);
  return d
    .toISOString()
    .replace(/\.\d{3}Z$/, "Z")
    .replaceAll(/[-:]/g, "");
}

/** Normalise any offset datetime to UTC ISO-8601 (no milliseconds). */
export function utcIso(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) throw new Error(`unparseable datetime: ${iso}`);
  return d.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function revisionRkey(abbr: string, observedAt: string): string {
  return `${abbr}-${compactUtc(observedAt)}`;
}

export function documentUri(abbr: string): string {
  return `at://${TRACKER_DID}/${DOCUMENT_COLLECTION}/${abbr}`;
}

export function statementUri(abbr: string): string {
  return `at://${TRACKER_DID}/${STATEMENT_COLLECTION}/${abbr}`;
}

export function revisionUri(abbr: string, observedAt: string): string {
  return `at://${TRACKER_DID}/${REVISION_COLLECTION}/${revisionRkey(abbr, observedAt)}`;
}

/** Site-root-relative path of a statement page (the Pages site serves from a base path). */
export function documentPath(abbr: string): string {
  return `${BASE_PATH}/statements/${abbr}`;
}

/**
 * Reduce statement markdown to the plain text site.standard.document readers
 * expect in textContent. The corpus is plain markdown (no JSX/frontmatter), so
 * this only needs to strip structural syntax, keeping link/image text.
 */
export function toPlainText(markdown: string): string {
  return markdown
    .replaceAll(/```[\s\S]*?```/g, " ")
    .replaceAll(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replaceAll(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replaceAll(/`([^`]+)`/g, "$1")
    .replaceAll(/^\s{0,3}#{1,6}\s+/gm, "")
    .replaceAll(/^\s{0,3}>\s?/gm, "")
    .replaceAll(/^\s{0,3}(?:[-*+]|\d+\.)\s+/gm, "")
    .replaceAll(/^_{3,}\s*$/gm, " ")
    .replaceAll(/(\*\*|__|~~)/g, "")
    .replaceAll(/\s+/g, " ")
    .trim();
}

/** The slice of the exporter's per-statement JSON the record builders need. */
export interface StatementInput {
  abbr: string;
  agency: string;
  sourceUrl: string;
  body: string;
  timeline: RevisionInput[];
}

export interface RevisionInput {
  sha: string;
  date: string;
  subject: string;
  message: string;
  kind: string;
  isNoise: boolean;
  charDelta: number;
  body: string;
}

interface RgbColor {
  r: number;
  g: number;
  b: number;
}

function themeColor(c: RgbColor) {
  return { $type: "site.standard.theme.color#rgb", ...c };
}

// The site's design tokens (src/styles/tokens.css) converted from oklch to
// sRGB: --bg, --text, --accent (the ochre signature), --accent-contrast.
const THEME = {
  background: { r: 249, g: 251, b: 252 },
  foreground: { r: 23, g: 29, b: 40 },
  accent: { r: 205, g: 124, b: 25 },
  accentForeground: { r: 37, g: 19, b: 4 },
};

export function buildPublicationRecord(iconBlob?: unknown): Record<string, unknown> {
  const record: Record<string, unknown> = {
    $type: PUBLICATION_COLLECTION,
    url: SITE_URL,
    name: "APS AI Tracker",
    description:
      "Tracking how Australian Government agencies describe their use of AI — " +
      "the full text of every AI transparency statement, a timeline of every change, " +
      "and an explorer for how statements resemble each other.",
    basicTheme: {
      background: themeColor(THEME.background),
      foreground: themeColor(THEME.foreground),
      accent: themeColor(THEME.accent),
      accentForeground: themeColor(THEME.accentForeground),
    },
    preferences: { showInDiscover: true },
  };
  if (iconBlob) record.icon = iconBlob;
  return record;
}

/** The last substantive (non-noise) change, or undefined if only the initial capture. */
function lastChanged(statement: StatementInput): string | undefined {
  const real = statement.timeline.findLast((r) => r.kind === "updated" && !r.isNoise);
  return real ? utcIso(real.date) : undefined;
}

export function buildDocumentRecord(
  statement: StatementInput,
  bskyPostRef?: StrongRef,
): Record<string, unknown> {
  const firstObserved = statement.timeline[0]!.date;
  const record: Record<string, unknown> = {
    $type: DOCUMENT_COLLECTION,
    title: `${statement.agency} — AI transparency statement`,
    site: PUBLICATION_URI,
    path: documentPath(statement.abbr),
    textContent: toPlainText(statement.body),
    publishedAt: utcIso(firstObserved),
    description:
      `The AI transparency statement of ${statement.agency}, captured from the agency's ` +
      `website and tracked for changes by the APS AI Tracker.`,
    tags: ["ai-transparency", "australian-government"],
  };
  const updated = lastChanged(statement);
  if (updated && updated !== utcIso(firstObserved)) record.updatedAt = updated;
  if (bskyPostRef) record.bskyPostRef = { uri: bskyPostRef.uri, cid: bskyPostRef.cid };
  return record;
}

export function buildStatementRecord(
  statement: StatementInput,
  contentHash: string,
): Record<string, unknown> {
  const record: Record<string, unknown> = {
    $type: STATEMENT_COLLECTION,
    abbr: statement.abbr,
    name: statement.agency,
    sourceUrl: statement.sourceUrl,
    document: documentUri(statement.abbr),
    firstObservedAt: utcIso(statement.timeline[0]!.date),
    contentHash,
    revisionCount: statement.timeline.length,
  };
  const updated = lastChanged(statement);
  if (updated) record.lastChangedAt = updated;
  return record;
}

export function buildRevisionRecord(
  abbr: string,
  revision: RevisionInput,
  contentHash: string,
  prev: RevisionInput | undefined,
): Record<string, unknown> {
  const record: Record<string, unknown> = {
    $type: REVISION_COLLECTION,
    statement: statementUri(abbr),
    abbr,
    observedAt: utcIso(revision.date),
    kind: revision.kind,
    isNoise: revision.isNoise,
    text: revision.body,
    contentHash,
  };
  if (revision.kind === "updated") record.charDelta = revision.charDelta;
  const note = [revision.subject, revision.message].filter(Boolean).join("\n\n").trim();
  if (note) record.note = note.slice(0, 10000);
  record.commitSha = revision.sha;
  if (prev) record.prev = revisionUri(abbr, prev.date);
  return record;
}

// --- change announcements (Bluesky cross-posting) ---------------------------

/** A record's AT-URI paired with the CID of its exact contents. */
export interface StrongRef {
  uri: string;
  cid: string;
}

/** One entry per announced (or deliberately skipped) revision rkey. */
export type LedgerEntry = { seeded: true } | (StrongRef & { syndicatedAt: string });

export type Ledger = Record<string, LedgerEntry>;

export interface Announcement {
  abbr: string;
  agency: string;
  rkey: string;
  revision: RevisionInput;
}

/** Only substantive events get announced; scrape noise never does. */
function announceable(rev: RevisionInput): boolean {
  return !rev.isNoise && ["added", "tracked-since", "updated"].includes(rev.kind);
}

/**
 * Decide which revisions to announce this run: any announceable revision with
 * no ledger entry, at most one per agency (the newest — catching up on a gap
 * shouldn't spam one skeet per missed revision), capped overall as a guard
 * against mass-change events. Everything passed over is returned in autoSeed
 * so the caller marks it seeded and it never resurfaces.
 */
export function planAnnouncements(
  statements: StatementInput[],
  ledger: Ledger,
  cap = 25,
): { announce: Announcement[]; autoSeed: string[] } {
  const announce: Announcement[] = [];
  const autoSeed: string[] = [];
  for (const st of statements) {
    const fresh = st.timeline.filter(
      (rev) => announceable(rev) && !(revisionRkey(st.abbr, rev.date) in ledger),
    );
    if (!fresh.length) continue;
    const newest = fresh.at(-1)!;
    announce.push({
      abbr: st.abbr,
      agency: st.agency,
      rkey: revisionRkey(st.abbr, newest.date),
      revision: newest,
    });
    for (const rev of fresh.slice(0, -1)) autoSeed.push(revisionRkey(st.abbr, rev.date));
  }
  announce.sort((a, b) => (a.revision.date < b.revision.date ? -1 : 1));
  const capped = announce.slice(0, cap);
  for (const a of announce.slice(cap)) autoSeed.push(a.rkey);
  return { announce: capped, autoSeed };
}

/** Skeet text for one announcement. Factual, agency-first, under 300 graphemes. */
export function announcementText(a: Announcement): string {
  let text: string;
  if (a.revision.kind === "updated") {
    const delta = a.revision.charDelta;
    const phrase =
      delta === 0
        ? "wording changes"
        : `${delta > 0 ? "+" : "−"}${Math.abs(delta).toLocaleString("en-AU")} characters`;
    text = `${a.agency} has updated its AI transparency statement (${phrase}).`;
  } else if (a.revision.kind === "added") {
    text = `${a.agency} has published an AI transparency statement.`;
  } else {
    text = `Now tracking the AI transparency statement of ${a.agency}.`;
  }
  return text.length > 300 ? `${text.slice(0, 299)}…` : text;
}

/**
 * The most recent announcement skeet for an agency, from the ledger — used as
 * the document record's bskyPostRef. Revision rkeys sort chronologically
 * within an agency, so the lexicographic max is the newest.
 */
export function latestPostRef(ledger: Ledger, abbr: string): StrongRef | undefined {
  const rkeys = Object.keys(ledger)
    .filter((k) => k.startsWith(`${abbr}-`) && "uri" in ledger[k]!)
    .toSorted();
  const newest = rkeys.at(-1);
  return newest ? (ledger[newest] as StrongRef) : undefined;
}
