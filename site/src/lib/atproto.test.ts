import { describe, expect, it } from "vitest";
import {
  buildDocumentRecord,
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
});
