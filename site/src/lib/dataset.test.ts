import { describe, expect, it } from "vitest";
import { CSV_HEADER, agencyCsvRow, publicStatement, toCsv } from "./dataset";
import type { AgencyRow, StatementDoc } from "@/types/exporter";

const currency = {
  statedLastUpdated: "2026-01-10",
  statedFirstPublished: null,
  lastContentChange: "2026-02-01T03:00:00+11:00",
  firstSeen: "2025-11-11T17:12:58+11:00",
  updatedSincePolicyV2: true,
  annualReviewOverdue: false,
  evaluatedAt: "2026-08-28",
};

const agency: AgencyRow = {
  abbr: "TEST",
  name: "Test Agency, of Testing",
  size: "small",
  scope: "mandatory",
  portfolio: "Finance",
  established: null,
  url: "https://example.gov.au/ai",
  status: "published",
  statementId: "TEST",
  firstSeen: "2025-11-11T17:12:58+11:00",
  lastUpdated: "2026-02-01T03:00:00+11:00",
  revisionCount: 3,
  changeCount: 1,
  originality: 0.42,
  currency,
};

const doc = {
  abbr: "TEST",
  agency: "Test Agency, of Testing",
  title: "AI transparency statement",
  sourceUrl: "https://example.gov.au/ai",
  sourceType: "html",
  body: "# Statement\n\nWe use AI.",
  frontmatter: {},
  timeline: [
    {
      sha: "abc123",
      date: "2025-11-11T17:12:58+11:00",
      subject: "initial commit",
      message: "",
      kind: "tracked-since",
      changeKind: "first-seen",
      changeMethod: "rule",
      summary: null,
      noteworthy: [],
      model: null,
      profileDeltas: [],
      isNoise: false,
      chars: 24,
      charDelta: 24,
      body: "# Statement\n\nWe use AI.",
    },
  ],
  passages: [],
  originality: { score: 0.42, shared: 2, unique: 5, sharedChars: 100, totalChars: 500 },
  profile: {
    summary: 'Says it uses AI for "testing", carefully.',
    intentions_stated: true,
    usage_patterns: ["workplace-productivity", "analytics-for-insights"],
    domains: ["corporate-and-enabling"],
    public_facing: "none",
    public_interaction_commitment: false,
    monitoring_measures_stated: true,
    measures: ["risk-assessment", "staff-training"],
    accountable_official: "designated",
    accountable_official_role: "Chief Operating Officer",
    chief_ai_officer: "in-place",
    chief_ai_officer_role: null,
    use_case_register: "not-mentioned",
    staff_training: "mandatory",
    strategic_position: "planned",
    review_cadence: "annual",
    first_published_stated: null,
    last_updated_stated: "2026-01-10",
    contact_provided: true,
    named_tools: ["Microsoft 365 Copilot"],
    policy_version: "v2",
    policy_compliance_stated: true,
    legislation_compliance_stated: false,
    commitments: [
      { text: "We will not use AI for decisions", kind: "will-not" },
      { text: "We will review annually", kind: "will" },
    ],
  },
  profileModel: "claude-opus-5",
  standard: {
    intentions: true,
    classification: true,
    "public-facing": true,
    monitoring: true,
    "policy-compliance": true,
    legislation: false,
    "last-updated": true,
    contact: true,
  },
  currency,
  latestCaptureSuspect: false,
} satisfies StatementDoc;

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
