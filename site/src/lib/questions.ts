// The questions a reader brings to the data, as filters. Each one is a fact
// about what a statement says (or about the body that published it), never a
// verdict on the agency: the labels say "say" and "don't mention" for that
// reason. Pure functions over the exporter's JSON, so the pages stay thin and
// the rules are tested in one place.
import { requirementFor, type FieldSource } from "@/lib/profile-labels";
import type { AgencyRow, StatementDoc, TimelineRevision } from "@/types/exporter";

// A statement whose own words are under this share of its text is "mostly
// shared or template wording". The originality score is by length.
const MOSTLY_SHARED = 1 / 3;

export const AGENCY_QUESTIONS: { key: string; label: string }[] = [
  { key: "mandatory", label: "Are required to publish" },
  { key: "all-eight", label: "Cover all eight Standard elements" },
  { key: "not-all-eight", label: "Miss at least one Standard element" },
  { key: "not-since-v2", label: "No update seen since policy v2.0" },
  { key: "dated-over-a-year", label: "Say they were last updated over a year ago" },
  { key: "caio", label: "Say a Chief AI Officer is in place" },
  { key: "no-caio", label: "Don't mention a Chief AI Officer" },
  { key: "no-public", label: "Say they use no public-facing AI" },
  { key: "public-no-review", label: "Say they use public-facing AI, without stating human review" },
  { key: "human-intermediary", label: "Commit to a human intermediary for public-facing AI" },
  { key: "dropped-commitment", label: "Dropped a commitment between versions" },
  { key: "mostly-shared", label: "Mostly shared or template wording" },
];

/** Which agency questions a published statement answers "yes" to. */
export function agencyAnswers(agency: AgencyRow, doc: StatementDoc | undefined): string[] {
  const keys: string[] = [];
  if (agency.scope === "mandatory") keys.push("mandatory");
  if (agency.originality !== null && agency.originality < MOSTLY_SHARED) keys.push("mostly-shared");
  if (!doc) return keys;

  if (doc.standard) {
    keys.push(Object.values(doc.standard).every(Boolean) ? "all-eight" : "not-all-eight");
  }
  if (doc.currency.updatedSincePolicyV2 === false) keys.push("not-since-v2");
  if (doc.currency.annualReviewOverdue === true) keys.push("dated-over-a-year");

  const p = doc.profile;
  if (p) {
    if (p.chief_ai_officer === "in-place") keys.push("caio");
    if (p.chief_ai_officer === "not-mentioned") keys.push("no-caio");
    if (p.public_facing === "none") keys.push("no-public");
    if (p.public_facing === "without-human-review") keys.push("public-no-review");
    if (p.public_interaction_commitment) keys.push("human-intermediary");
  }
  const droppedCommitment = doc.timeline.some((rev) =>
    rev.profileDeltas.some((d) => d.field === "commitments" && d.direction === "removed"),
  );
  if (droppedCommitment) keys.push("dropped-commitment");
  return keys;
}

/** What a change did to a statement's answers, as "requirement:direction"
 * pairs ("commitments:removed"), so a filter on both finds a dropped
 * commitment rather than any change that touched commitments and dropped
 * something else. */
export function changeFacets(rev: Pick<TimelineRevision, "profileDeltas">): string[] {
  const facets = new Set<string>();
  for (const d of rev.profileDeltas) {
    const req = requirementFor(d.field);
    if (req) facets.add(`${req.key}:${d.direction}`);
  }
  return [...facets];
}

// The "about" filter's groups, in the instruments' order.
export const SOURCE_GROUP_LABEL: Record<FieldSource, string> = {
  standard: "The Standard",
  policy: "Policy v2.0",
  "ai-plan": "APS AI Plan",
  tracker: "The tracker's own questions",
};
