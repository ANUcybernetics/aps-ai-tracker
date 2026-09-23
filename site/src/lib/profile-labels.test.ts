import { describe, expect, it } from "vitest";
import { REQUIREMENTS, STANDARD_ELEMENTS, requirementFor } from "@/lib/profile-labels";
import { profileSchema } from "@/lib/schemas";

// Free text and the role titles that qualify another answer are not questions
// of their own.
const NOT_QUESTIONS = new Set(["summary", "accountable_official_role", "chief_ai_officer_role"]);

describe("REQUIREMENTS", () => {
  it("files every profile field under exactly one requirement", () => {
    const fields = Object.keys(profileSchema.shape).filter((f) => !NOT_QUESTIONS.has(f));
    const filed = REQUIREMENTS.flatMap((r) => r.fields);
    expect(filed.toSorted()).toEqual(fields.toSorted());
    for (const f of fields) expect(requirementFor(f)).toBeDefined();
  });

  it("lists the Standard's eight minimum elements first, in order", () => {
    expect(STANDARD_ELEMENTS.map((e) => e.key)).toEqual([
      "intentions",
      "classification",
      "public-facing",
      "monitoring",
      "policy-compliance",
      "legislation",
      "last-updated",
      "contact",
    ]);
    expect(REQUIREMENTS.slice(0, 8)).toEqual(STANDARD_ELEMENTS);
  });
});
