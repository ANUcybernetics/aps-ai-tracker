// The downloadable dataset: flattening helpers shared by the /data endpoints
// (src/pages/data/*). Pure functions over the exporter types so they can be
// unit-tested without a build.
import type { AgencyRow, Meta, StatementDoc, TimelineRevision } from "@/types/exporter";

// Provenance stamped into every JSON download, so a file that escapes into a
// notebook still says where and when it came from and which schema vintage
// produced its fields.
export function provenance(meta: Meta) {
  return {
    generatedAt: meta.builtAt,
    headSha: meta.headSha,
    schemaVersions: meta.schemaVersions,
    source: "https://github.com/ANUcybernetics/aps-ai-tracker",
    docs: "https://apsaitracker.app/data/",
    license: "CC-BY-4.0",
    note: "Profile and change fields are a language model's reading of each statement; see https://apsaitracker.app/reading/ for what each figure does and does not claim.",
  };
}

// RFC 4180: quote a cell when it contains a comma, quote, or newline; double
// embedded quotes. Booleans render as true/false, null as an empty cell.
export type Cell = string | number | boolean | null;

function csvCell(value: Cell): string {
  if (value === null) return "";
  const s = String(value);
  return /[",\n\r]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

export function toCsv(header: string[], rows: Cell[][]): string {
  const lines = [header, ...rows.map((r) => r.map((c) => csvCell(c)))];
  return lines.map((cells) => cells.join(",")).join("\n") + "\n";
}

// One row per tracked agency (including those with no statement, so the
// coverage gaps are in the file too). Column order here is the file's public
// shape — append rather than reorder when adding columns.
export const CSV_HEADER = [
  "abbr",
  "name",
  "portfolio",
  "scope",
  "status",
  "url",
  "first_seen",
  "last_content_change",
  "revision_count",
  "change_count",
  "originality",
  "stated_first_published",
  "stated_last_updated",
  "updated_since_policy_v2",
  "annual_review_overdue",
  "standard_intentions",
  "standard_classification",
  "standard_public_facing",
  "standard_monitoring",
  "standard_policy_compliance",
  "standard_legislation",
  "standard_last_updated",
  "standard_contact",
  "profile_model",
  "intentions_stated",
  "usage_patterns",
  "domains",
  "public_facing",
  "public_interaction_commitment",
  "monitoring_measures_stated",
  "measures",
  "accountable_official",
  "accountable_official_role",
  "chief_ai_officer",
  "chief_ai_officer_role",
  "use_case_register",
  "staff_training",
  "strategic_position",
  "review_cadence",
  "contact_provided",
  "named_tools",
  "policy_version",
  "policy_compliance_stated",
  "legislation_compliance_stated",
  "commitments_count",
  "will_not_count",
  "profile_summary",
];

// Keys match profiles.py STANDARD_ELEMENTS / profile-labels.ts, in CSV_HEADER
// order.
const STANDARD_KEYS = [
  "intentions",
  "classification",
  "public-facing",
  "monitoring",
  "policy-compliance",
  "legislation",
  "last-updated",
  "contact",
];

const joinList = (items: string[]): string => items.join("; ");

export function agencyCsvRow(agency: AgencyRow, doc: StatementDoc | undefined): Cell[] {
  const c = agency.currency;
  const p = doc?.profile ?? null;
  const standard = doc?.standard ?? null;
  return [
    agency.abbr,
    agency.name,
    agency.portfolio,
    agency.scope,
    agency.status,
    agency.url,
    agency.firstSeen,
    c?.lastContentChange ?? null,
    agency.revisionCount,
    agency.changeCount,
    agency.originality,
    c?.statedFirstPublished ?? null,
    c?.statedLastUpdated ?? null,
    c?.updatedSincePolicyV2 ?? null,
    c?.annualReviewOverdue ?? null,
    ...STANDARD_KEYS.map((k) => standard?.[k] ?? null),
    doc?.profileModel ?? null,
    ...(p === null
      ? Array<Cell>(23).fill(null)
      : [
          p.intentions_stated,
          joinList(p.usage_patterns),
          joinList(p.domains),
          p.public_facing,
          p.public_interaction_commitment,
          p.monitoring_measures_stated,
          joinList(p.measures),
          p.accountable_official,
          p.accountable_official_role,
          p.chief_ai_officer,
          p.chief_ai_officer_role,
          p.use_case_register,
          p.staff_training,
          p.strategic_position,
          p.review_cadence,
          p.contact_provided,
          joinList(p.named_tools),
          p.policy_version,
          p.policy_compliance_stated,
          p.legislation_compliance_stated,
          p.commitments.length,
          p.commitments.filter((cm) => cm.kind === "will-not").length,
          p.summary,
        ]),
  ];
}

// The JSON download's revision entries: the statement doc's timeline minus the
// full body text and the git commit plumbing (a scrape commit describes the
// whole batch, not one file).
function publicRevision(rev: TimelineRevision) {
  const { body: _body, subject: _subject, message: _message, ...rest } = rev;
  return rest;
}

// The JSON download's per-statement record: the statement doc joined with its
// roster row, minus body text and passage internals. Bodies live in the git
// repo (statements/) and on the AT Protocol mirror.
export function publicStatement(agency: AgencyRow, doc: StatementDoc) {
  return {
    abbr: doc.abbr,
    agency: doc.agency,
    portfolio: agency.portfolio,
    scope: agency.scope,
    status: agency.status,
    title: doc.title,
    sourceUrl: doc.sourceUrl,
    sourceType: doc.sourceType,
    latestCaptureSuspect: doc.latestCaptureSuspect,
    originality: doc.originality,
    currency: doc.currency,
    standard: doc.standard,
    profile: doc.profile,
    profileModel: doc.profileModel,
    revisions: doc.timeline.map((rev) => publicRevision(rev)),
  };
}
