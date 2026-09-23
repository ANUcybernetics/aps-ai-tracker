import { describe, expect, it } from "vitest";
import { agencyAnswers, changeFacets } from "./questions";
import { agency, doc } from "./__fixtures__/statement";
import type { ProfileDelta } from "@/types/exporter";

const delta = (field: string, direction: ProfileDelta["direction"]): ProfileDelta => ({
  field,
  label: field,
  direction,
  before: null,
  after: null,
});

describe("agencyAnswers", () => {
  it("answers from what the statement says and who published it", () => {
    // The fixture: mandatory, 42% own words, 7 of 8 elements, CAIO in place,
    // no public-facing AI, no commitment dropped.
    expect(agencyAnswers(agency, doc).toSorted()).toEqual(
      ["caio", "mandatory", "no-public", "not-all-eight"].toSorted(),
    );
  });

  it("counts a dropped commitment in any revision", () => {
    const rev = { ...doc.timeline[0], profileDeltas: [delta("commitments", "removed")] };
    expect(agencyAnswers(agency, { ...doc, timeline: [rev] })).toContain("dropped-commitment");
  });

  it("marks a statement mostly shared when under a third is its own", () => {
    expect(agencyAnswers({ ...agency, originality: 0.2 }, doc)).toContain("mostly-shared");
  });

  it("answers only roster questions for a body with no statement", () => {
    expect(agencyAnswers(agency, undefined)).toEqual(["mandatory"]);
  });
});

describe("changeFacets", () => {
  it("pairs each delta's requirement with its direction", () => {
    const facets = changeFacets({
      profileDeltas: [
        delta("usage_patterns", "added"),
        delta("domains", "removed"),
        delta("chief_ai_officer", "added"),
        delta("commitments", "added"),
      ],
    });
    expect(facets.toSorted()).toEqual([
      "chief-ai-officer:added",
      "classification:added",
      "classification:removed",
      "commitments:added",
    ]);
  });
});
