import { describe, expect, it } from "vitest";
import {
  announcementText,
  buildDocumentRecord,
  latestPostRef,
  planAnnouncements,
  type Ledger,
  buildPublicationRecord,
  buildRevisionRecord,
  buildStatementRecord,
  compactUtc,
  documentPath,
  documentUri,
  PUBLICATION_URI,
  revisionRkey,
  revisionUri,
  statementUri,
  toPlainText,
  TRACKER_DID,
  utcIso,
  type RevisionInput,
  type StatementInput,
} from "./atproto";

const rev = (over: Partial<RevisionInput> = {}): RevisionInput => ({
  sha: "07278a5dff0881f75398176c9044605634baf8f3",
  date: "2025-11-11T17:12:58+11:00",
  subject: "initial commit of 57 transparency statements",
  message: "",
  kind: "tracked-since",
  isNoise: false,
  charDelta: 6205,
  body: "# AI transparency statement\n\nSome body text.",
  ...over,
});

const statement = (over: Partial<StatementInput> = {}): StatementInput => ({
  abbr: "ABS",
  agency: "Australian Bureau of Statistics",
  sourceUrl: "https://www.abs.gov.au/about/legislation-and-policy/ai-transparency-statement",
  body: "# AI transparency statement\n\nCurrent body.",
  timeline: [rev()],
  ...over,
});

describe("deterministic identifiers", () => {
  it("compacts offset datetimes to UTC", () => {
    expect(compactUtc("2025-11-11T17:12:58+11:00")).toBe("20251111T061258Z");
    expect(compactUtc("2026-07-11T03:23:10+10:00")).toBe("20260710T172310Z");
  });

  it("normalises datetimes to UTC ISO without milliseconds", () => {
    expect(utcIso("2025-11-11T17:12:58+11:00")).toBe("2025-11-11T06:12:58Z");
  });

  it("throws on garbage datetimes rather than minting a bad rkey", () => {
    expect(() => compactUtc("not a date")).toThrow(/unparseable/);
  });

  it("builds rkeys and AT-URIs from abbr + observation time alone", () => {
    expect(revisionRkey("ABS", "2025-11-11T17:12:58+11:00")).toBe("ABS-20251111T061258Z");
    expect(documentUri("ABS")).toBe(`at://${TRACKER_DID}/site.standard.document/ABS`);
    expect(statementUri("ABS")).toBe(`at://${TRACKER_DID}/me.benswift.transparencyStatement/ABS`);
    expect(revisionUri("ABS", "2025-11-11T17:12:58+11:00")).toBe(
      `at://${TRACKER_DID}/me.benswift.transparencyStatementRevision/ABS-20251111T061258Z`,
    );
  });

  it("statement pages live under the Pages base path", () => {
    expect(documentPath("ABS")).toBe("/aps-ai-transparency-tracker/statements/ABS");
  });
});

describe("toPlainText", () => {
  it("strips markdown structure but keeps link text", () => {
    const md = "# Heading\n\nSee [the policy](https://example.gov.au) and `code`.\n\n- item one\n";
    expect(toPlainText(md)).toBe("Heading See the policy and code. item one");
  });

  it("collapses whitespace and horizontal rules", () => {
    expect(toPlainText("a\n\n______________\n\nb")).toBe("a b");
  });
});

describe("record builders", () => {
  it("publication record targets the Pages site and opts into discovery", () => {
    const record = buildPublicationRecord();
    expect(record.$type).toBe("site.standard.publication");
    expect(record.url).toBe("https://anucybernetics.github.io/aps-ai-transparency-tracker/");
    expect(record.preferences).toEqual({ showInDiscover: true });
    expect(record.icon).toBeUndefined();
  });

  it("document record carries plaintext, path and publishedAt from first observation", () => {
    const record = buildDocumentRecord(statement());
    expect(record.site).toBe(PUBLICATION_URI);
    expect(record.path).toBe("/aps-ai-transparency-tracker/statements/ABS");
    expect(record.textContent).toBe("AI transparency statement Current body.");
    expect(record.publishedAt).toBe("2025-11-11T06:12:58Z");
    expect(record.updatedAt).toBeUndefined();
  });

  it("substantive updates set updatedAt/lastChangedAt; noise does not", () => {
    const noisy = statement({
      timeline: [rev(), rev({ kind: "updated", isNoise: true, date: "2026-07-07T17:08:42+10:00" })],
    });
    expect(buildDocumentRecord(noisy).updatedAt).toBeUndefined();
    expect(buildStatementRecord(noisy, "abc").lastChangedAt).toBeUndefined();

    const changed = statement({
      timeline: [rev(), rev({ kind: "updated", date: "2026-07-07T17:08:42+10:00" })],
    });
    expect(buildDocumentRecord(changed).updatedAt).toBe("2026-07-07T07:08:42Z");
    expect(buildStatementRecord(changed, "abc").lastChangedAt).toBe("2026-07-07T07:08:42Z");
  });

  it("statement record links its document and counts revisions", () => {
    const record = buildStatementRecord(statement(), "deadbeef");
    expect(record).toMatchObject({
      $type: "me.benswift.transparencyStatement",
      abbr: "ABS",
      document: documentUri("ABS"),
      contentHash: "deadbeef",
      revisionCount: 1,
      firstObservedAt: "2025-11-11T06:12:58Z",
    });
  });

  it("revision records chain via prev and keep full text", () => {
    const first = rev();
    const second = rev({
      kind: "updated",
      date: "2026-07-07T17:08:42+10:00",
      charDelta: -25,
      body: "new body",
    });
    const record = buildRevisionRecord("ABS", second, "hash2", first);
    expect(record).toMatchObject({
      $type: "me.benswift.transparencyStatementRevision",
      statement: statementUri("ABS"),
      observedAt: "2026-07-07T07:08:42Z",
      kind: "updated",
      charDelta: -25,
      text: "new body",
      prev: revisionUri("ABS", first.date),
    });

    const initial = buildRevisionRecord("ABS", first, "hash1", undefined);
    expect(initial.prev).toBeUndefined();
    expect(initial.charDelta).toBeUndefined();
  });

  it("builders are deterministic: same input, byte-identical JSON", () => {
    const a = JSON.stringify(buildRevisionRecord("ABS", rev(), "h", undefined));
    const b = JSON.stringify(buildRevisionRecord("ABS", rev(), "h", undefined));
    expect(a).toBe(b);
  });

  it("document record carries bskyPostRef when the ledger has an announcement", () => {
    const ref = { uri: "at://did:plc:x/app.bsky.feed.post/3k", cid: "bafy123" };
    expect(buildDocumentRecord(statement(), ref).bskyPostRef).toEqual(ref);
    expect(buildDocumentRecord(statement()).bskyPostRef).toBeUndefined();
  });
});

describe("announcements", () => {
  const updated = (date: string, over: Partial<RevisionInput> = {}) =>
    rev({ kind: "updated", date, ...over });

  it("announces only unledgered, substantive revisions", () => {
    const sts = [
      statement({ timeline: [rev(), updated("2026-07-01T10:00:00+10:00")] }),
      statement({
        abbr: "XYZ",
        agency: "Xyz Authority",
        timeline: [rev(), updated("2026-07-02T10:00:00+10:00", { isNoise: true })],
      }),
    ];
    const ledger: Ledger = { "ABS-20251111T061258Z": { seeded: true } };
    const { announce, autoSeed } = planAnnouncements(sts, ledger);
    // ABS's first revision is seeded and XYZ's update is noise; XYZ's initial
    // tracked-since revision IS announceable (it has no ledger entry).
    expect(announce.map((a) => a.rkey)).toEqual(["XYZ-20251111T061258Z", "ABS-20260701T000000Z"]);
    expect(autoSeed).toEqual([]);
  });

  it("announces at most the newest revision per agency, auto-seeding the rest", () => {
    const sts = [
      statement({
        timeline: [
          rev(),
          updated("2026-07-01T10:00:00+10:00"),
          updated("2026-07-03T10:00:00+10:00"),
        ],
      }),
    ];
    const ledger: Ledger = { "ABS-20251111T061258Z": { seeded: true } };
    const { announce, autoSeed } = planAnnouncements(sts, ledger);
    expect(announce.map((a) => a.rkey)).toEqual(["ABS-20260703T000000Z"]);
    expect(autoSeed).toEqual(["ABS-20260701T000000Z"]);
  });

  it("caps a mass-change run, auto-seeding the overflow", () => {
    const sts = Array.from({ length: 30 }, (_, i) =>
      statement({
        abbr: `AG${i}`,
        timeline: [rev(), updated("2026-07-01T10:00:00+10:00")],
      }),
    );
    const ledger: Ledger = Object.fromEntries(
      sts.map((st) => [`${st.abbr}-20251111T061258Z`, { seeded: true }]),
    );
    const { announce, autoSeed } = planAnnouncements(sts, ledger, 25);
    expect(announce).toHaveLength(25);
    expect(autoSeed).toHaveLength(5);
  });

  it("phrases each kind factually", () => {
    const base = { abbr: "ABS", agency: "Australian Bureau of Statistics", rkey: "x" };
    expect(
      announcementText({ ...base, revision: updated("2026-07-01", { charDelta: -214 }) }),
    ).toBe(
      "Australian Bureau of Statistics has updated its AI transparency statement (−214 characters).",
    );
    expect(
      announcementText({ ...base, revision: updated("2026-07-01", { charDelta: 1234 }) }),
    ).toBe(
      "Australian Bureau of Statistics has updated its AI transparency statement (+1,234 characters).",
    );
    expect(announcementText({ ...base, revision: updated("2026-07-01", { charDelta: 0 }) })).toBe(
      "Australian Bureau of Statistics has updated its AI transparency statement (wording changes).",
    );
    expect(announcementText({ ...base, revision: rev({ kind: "added" }) })).toBe(
      "Australian Bureau of Statistics has published an AI transparency statement.",
    );
    expect(announcementText({ ...base, revision: rev() })).toBe(
      "Now tracking the AI transparency statement of Australian Bureau of Statistics.",
    );
  });

  it("finds the newest announced skeet for an agency, ignoring lookalike abbrs", () => {
    const ledger: Ledger = {
      "ABS-20251111T061258Z": { seeded: true },
      "ABS-20260501T002837Z": { uri: "at://x/post/old", cid: "c1", syndicatedAt: "t" },
      "ABS-20260601T002837Z": { uri: "at://x/post/new", cid: "c2", syndicatedAt: "t" },
      "ABSA-20260701T002837Z": { uri: "at://x/post/other", cid: "c3", syndicatedAt: "t" },
    };
    expect(latestPostRef(ledger, "ABS")?.uri).toBe("at://x/post/new");
    expect(latestPostRef(ledger, "AASB")).toBeUndefined();
  });
});
