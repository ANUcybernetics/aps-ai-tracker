import { describe, expect, it } from "vitest";
import { revisionBodyToHtml } from "./revision-html";

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

  it("escapes inline raw HTML inside a paragraph", () => {
    const html = revisionBodyToHtml("an <img src=x onerror=alert(1)> inline");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });

  it("renders safe links with the external-link attributes", () => {
    const html = revisionBodyToHtml("[policy](https://www.digital.gov.au/ai)");
    expect(html).toContain(
      '<a href="https://www.digital.gov.au/ai" target="_blank" rel="noopener noreferrer">policy</a>',
    );
  });

  it("drops dangerous link schemes but keeps the label text", () => {
    const html = revisionBodyToHtml("[click](javascript:alert(1))");
    expect(html).not.toContain("<a ");
    expect(html).toContain("click");
  });

  it("replaces images with an alt-text placeholder", () => {
    const html = revisionBodyToHtml("![Pigeonholes](https://example.gov.au/x.webp)\n\ntext");
    expect(html).not.toContain("<img");
    expect(html).toContain("[image: Pigeonholes]");
  });

  it("drops alt-less images entirely", () => {
    const html = revisionBodyToHtml("![](https://example.gov.au/x.webp)\n\ntext");
    expect(html).not.toContain("image:");
    expect(html).toContain("<p>text</p>");
  });
});
