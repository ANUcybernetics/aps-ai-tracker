import { describe, expect, it } from "vitest";
import {
  escapeHtml,
  inlineMarkdownToHtml,
  passageToHtml,
  revisionBodyToHtml,
  stripBlockMarkers,
} from "./markdown";

describe("escapeHtml", () => {
  it("escapes the HTML-significant characters", () => {
    expect(escapeHtml(`a & b < c > d " e ' f`)).toBe("a &amp; b &lt; c &gt; d &quot; e &#39; f");
  });
});

describe("inlineMarkdownToHtml", () => {
  it("renders a markdown link as an anchor", () => {
    expect(
      inlineMarkdownToHtml("see the [AI policy](https://www.digital.gov.au/ai) for details"),
    ).toBe(
      'see the <a href="https://www.digital.gov.au/ai" target="_blank" rel="noopener noreferrer">AI policy</a> for details',
    );
  });

  it("renders multiple links in one passage", () => {
    const out = inlineMarkdownToHtml("[a](https://a.gov.au) and [b](https://b.gov.au)");
    expect(out).toContain('href="https://a.gov.au"');
    expect(out).toContain('href="https://b.gov.au"');
    expect(out.match(/<a /g)).toHaveLength(2);
  });

  it("escapes HTML in the surrounding text", () => {
    expect(inlineMarkdownToHtml("5 < 10 & rising")).toBe("5 &lt; 10 &amp; rising");
  });

  it("refuses dangerous link schemes, keeping only the label text", () => {
    const out = inlineMarkdownToHtml("[click](javascript:alert(1))");
    expect(out).not.toContain("<a ");
    expect(out).toContain("click");
  });

  it("replaces images with an alt-text placeholder", () => {
    const out = inlineMarkdownToHtml("![Pigeonholes](https://example.gov.au/x.webp) and text");
    expect(out).not.toContain("<img");
    expect(out).toContain("[image: Pigeonholes]");
  });

  it("escapes inline raw HTML", () => {
    const out = inlineMarkdownToHtml("an <img src=x onerror=alert(1)> inline");
    expect(out).not.toContain("<img");
    expect(out).toContain("&lt;img");
  });

  it("allows relative and fragment links", () => {
    expect(inlineMarkdownToHtml("[home](/index)")).toContain('href="/index"');
    expect(inlineMarkdownToHtml("[top](#top)")).toContain('href="#top"');
  });

  it("renders bold and italic", () => {
    expect(inlineMarkdownToHtml("**External facing:**")).toBe("<strong>External facing:</strong>");
    expect(inlineMarkdownToHtml("an _italic_ word")).toBe("an <em>italic</em> word");
  });

  it("renders inline code without interpreting its contents", () => {
    expect(inlineMarkdownToHtml("use `[notalink](x)` literally")).toBe(
      "use <code>[notalink](x)</code> literally",
    );
  });

  it("leaves plain text untouched", () => {
    expect(inlineMarkdownToHtml("just a sentence.")).toBe("just a sentence.");
  });
});

describe("stripBlockMarkers", () => {
  it("strips heading hashes", () => {
    expect(stripBlockMarkers("## Public interaction and impact")).toBe(
      "Public interaction and impact",
    );
    expect(stripBlockMarkers("# Artificial Intelligence (AI) statement")).toBe(
      "Artificial Intelligence (AI) statement",
    );
  });

  it("strips blockquote markers on every line", () => {
    expect(stripBlockMarkers("> An AI system is a machine-based system.")).toBe(
      "An AI system is a machine-based system.",
    );
    expect(stripBlockMarkers("> line one\n> line two")).toBe("line one\nline two");
  });

  it("strips a leading list marker", () => {
    expect(stripBlockMarkers("- a bullet point")).toBe("a bullet point");
    expect(stripBlockMarkers("1. a numbered point")).toBe("a numbered point");
  });

  it("leaves an unmarked paragraph alone", () => {
    expect(stripBlockMarkers("Just a normal sentence.")).toBe("Just a normal sentence.");
  });
});

describe("passageToHtml", () => {
  it("strips block scaffolding and renders inline links", () => {
    expect(passageToHtml("## See the [policy](https://www.digital.gov.au/ai)")).toBe(
      'See the <a href="https://www.digital.gov.au/ai" target="_blank" rel="noopener noreferrer">policy</a>',
    );
  });

  it("renders a quoted definition as plain prose", () => {
    expect(passageToHtml("> An AI system **infers** outputs.")).toBe(
      "An AI system <strong>infers</strong> outputs.",
    );
  });
});

describe("revisionBodyToHtml", () => {
  it("renders headings, paragraphs and lists", () => {
    const html = revisionBodyToHtml("## Usage\n\nSome text.\n\n- one\n- two\n");
    expect(html).toContain("Usage");
    expect(html).toContain("<p>Some text.</p>");
    expect(html).toContain("<li>one</li>");
  });

  it("demotes headings so the shallowest becomes h2", () => {
    const html = revisionBodyToHtml("# Title\n\n## Section\n");
    expect(html).toContain("<h2>Title</h2>");
    expect(html).toContain("<h3>Section</h3>");
    expect(html).not.toContain("<h1");
  });

  it("promotes overly deep heading hierarchies up to h2", () => {
    const html = revisionBodyToHtml("### Only section\n");
    expect(html).toContain("<h2>Only section</h2>");
  });

  it("clamps demoted headings at h6", () => {
    const html = revisionBodyToHtml("# a\n\n###### deep\n");
    expect(html).toContain("<h6>deep</h6>");
    expect(html).not.toContain("<h7");
  });

  it("renders nested lists (the html2text two-space style)", () => {
    const html = revisionBodyToHtml("  * outer\n    * inner one\n    * inner two\n");
    expect(html.match(/<ul>/g)?.length).toBe(2);
    expect(html).toContain("inner one");
  });

  it("renders GFM tables", () => {
    const html = revisionBodyToHtml("| Use | Domain |\n| --- | --- |\n| chatbot | service |\n");
    expect(html).toContain("<table>");
    expect(html).toContain("<td>chatbot</td>");
  });

  it("escapes raw HTML rather than passing it through", () => {
    const html = revisionBodyToHtml("before\n\n<script>alert(1)</script>\n\nafter");
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });

  it("renders safe links with the external-link attributes", () => {
    const html = revisionBodyToHtml("[policy](https://www.digital.gov.au/ai)");
    expect(html).toContain(
      '<a href="https://www.digital.gov.au/ai" target="_blank" rel="noopener noreferrer">policy</a>',
    );
  });

  it("drops alt-less images entirely", () => {
    const html = revisionBodyToHtml("![](https://example.gov.au/x.webp)\n\ntext");
    expect(html).not.toContain("image:");
    expect(html).toContain("<p>text</p>");
  });
});
