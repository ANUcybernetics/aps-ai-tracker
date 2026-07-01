import { describe, expect, it } from "vitest";
import { compactWordDiffHtml, wordDiffHtml } from "./diff";

describe("wordDiffHtml", () => {
  it("marks a single inserted word", () => {
    expect(wordDiffHtml("we use AI", "we use generative AI")).toBe(
      "we use <ins>generative </ins>AI",
    );
  });

  it("marks a single removed word", () => {
    expect(wordDiffHtml("we use generative AI", "we use AI")).toBe(
      "we use <del>generative </del>AI",
    );
  });

  it("escapes HTML in both changed and unchanged text", () => {
    expect(wordDiffHtml("a < b", "a > b")).toBe("a <del>&lt;</del><ins>&gt;</ins> b");
  });

  // The regression this file exists for: a wholesale paragraph rewrite must not
  // interleave del/ins word-by-word (the old "ArtificialACIAR's" soup). Semantic
  // cleanup should keep each side contiguous — one removal run, one addition run.
  it("renders a full rewrite as one removal then one addition, not interleaved", () => {
    const before = "Background AI simulates human intelligence processes.";
    const after = "Introduction ACIAR's commitment to responsible AI supports our mission.";
    const html = wordDiffHtml(before, after);
    // Exactly one <del> and one <ins> — no alternating runs.
    expect((html.match(/<del>/g) ?? []).length).toBe(1);
    expect((html.match(/<ins>/g) ?? []).length).toBe(1);
    // Every deleted-then-inserted region, and no <ins> before the <del>.
    expect(html.indexOf("<del>")).toBeLessThan(html.indexOf("<ins>"));
  });
});

describe("compactWordDiffHtml", () => {
  it("elides a long unchanged run while keeping the change", () => {
    const unchanged = "x".repeat(300);
    const html = compactWordDiffHtml(`${unchanged} old`, `${unchanged} new`);
    expect(html).toContain("&hellip;");
    expect(html).toContain("<del>old</del>");
    expect(html).toContain("<ins>new</ins>");
    expect(html).not.toContain(unchanged);
  });

  it("keeps short unchanged runs verbatim", () => {
    expect(compactWordDiffHtml("we use AI", "we use ML")).toBe("we use <del>AI</del><ins>ML</ins>");
  });
});
