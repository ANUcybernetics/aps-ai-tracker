import { describe, expect, it } from "vitest";
import { compactWordDiffHtml, hasStatementTextChange, wordDiffHtml } from "./diff";

describe("hasStatementTextChange", () => {
  it("ignores destination-only inline-link changes", () => {
    const before = "Read the [policy](https://example.gov.au/policy-v1.pdf).";
    const after = "Read the [policy](https://static.example.gov.au/policy-v2.pdf?rev=2).";
    expect(hasStatementTextChange(before, after)).toBe(false);
  });

  it("handles parentheses in link destinations", () => {
    const before = "Download it [here](https://example.gov.au/file%20(old).pdf).";
    const after = "Download it [here](https://example.gov.au/file%20(new).pdf).";
    expect(hasStatementTextChange(before, after)).toBe(false);
  });

  it("keeps changed link labels as statement text", () => {
    expect(
      hasStatementTextChange(
        "See the [2025 policy](https://example.gov.au/policy).",
        "See the [2026 policy](https://example.gov.au/policy).",
      ),
    ).toBe(true);
  });

  it("ignores a standalone link added by surrounding page chrome", () => {
    const before = "## Contact\n\nEmail the accountable official.";
    const after =
      "## Contact\n\nEmail the accountable official.\n\n[January–June 2026](https://example.gov.au/register.pdf)";
    expect(hasStatementTextChange(before, after)).toBe(false);
  });

  it("keeps a link added as part of prose", () => {
    expect(
      hasStatementTextChange(
        "We follow the government policy.",
        "We follow the [updated government policy](https://example.gov.au/policy).",
      ),
    ).toBe(true);
  });

  it("keeps ordinary prose changes", () => {
    expect(hasStatementTextChange("We trial AI.", "We deploy AI.")).toBe(true);
  });

  it("ignores the Parliament static-asset URL migration", () => {
    const before =
      "[DPS AI transparency statement (PDF, 286 KB)](https://www.aph.gov.au/-/media/DPS_AI_transparency_statement.pdf)";
    const after =
      "[DPS AI transparency statement (PDF, 286 KB)](https://static.aph.gov.au/-/media/DPS_AI_transparency_statement.pdf?rev=4a9c12dd&hash=C5A61F6A)";
    expect(hasStatementTextChange(before, after)).toBe(false);
  });

  it("does not let simultaneous URL churn mask a genuine edit", () => {
    const before = "We are trialling AI. Read the [policy](https://www.digital.gov.au/old-policy).";
    const after = "We are deploying AI. Read the [policy](https://www.digital.gov.au/new-policy).";
    expect(hasStatementTextChange(before, after)).toBe(true);
  });
});

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
