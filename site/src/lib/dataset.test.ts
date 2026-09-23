import { describe, expect, it } from "vitest";
import { CSV_HEADER, agencyCsvRow, publicStatement, toCsv } from "./dataset";
import { agency, doc } from "./__fixtures__/statement";
import type { AgencyRow } from "@/types/exporter";

describe("toCsv", () => {
  it("escapes commas, quotes and newlines per RFC 4180", () => {
    const csv = toCsv(["a", "b", "c"], [['say "hi"', "one, two", "line1\nline2"]]);
    expect(csv).toBe('a,b,c\n"say ""hi""","one, two","line1\nline2"\n');
  });

  it("renders booleans as true/false and null as an empty cell", () => {
    expect(toCsv(["x", "y", "z"], [[true, null, 0]])).toBe("x,y,z\ntrue,,0\n");
  });
});

describe("agencyCsvRow", () => {
  it("produces one cell per header column for a profiled statement", () => {
    const row = agencyCsvRow(agency, doc);
    expect(row).toHaveLength(CSV_HEADER.length);
    const get = (col: string) => row[CSV_HEADER.indexOf(col)];
    expect(get("abbr")).toBe("TEST");
    expect(get("usage_patterns")).toBe("workplace-productivity; analytics-for-insights");
    expect(get("standard_legislation")).toBe(false);
    expect(get("commitments_count")).toBe(2);
    expect(get("will_not_count")).toBe(1);
    expect(get("updated_since_policy_v2")).toBe(true);
    expect(get("profile_model")).toBe("claude-opus-5");
  });

  it("still lines up with the header when the agency has no statement", () => {
    const bare: AgencyRow = {
      ...agency,
      status: "not-yet",
      statementId: null,
      url: null,
      firstSeen: null,
      lastUpdated: null,
      revisionCount: 0,
      changeCount: 0,
      originality: null,
      currency: null,
    };
    const row = agencyCsvRow(bare, undefined);
    expect(row).toHaveLength(CSV_HEADER.length);
    expect(row[CSV_HEADER.indexOf("status")]).toBe("not-yet");
    expect(row[CSV_HEADER.indexOf("profile_summary")]).toBe(null);
  });
});

describe("publicStatement", () => {
  it("joins the roster row and strips bodies and commit plumbing", () => {
    const pub = publicStatement(agency, doc);
    expect(pub.portfolio).toBe("Finance");
    expect(pub).not.toHaveProperty("body");
    expect(pub).not.toHaveProperty("passages");
    expect(pub.revisions).toHaveLength(1);
    expect(pub.revisions[0]).not.toHaveProperty("body");
    expect(pub.revisions[0]).not.toHaveProperty("subject");
    expect(pub.revisions[0].changeKind).toBe("first-seen");
  });
});
