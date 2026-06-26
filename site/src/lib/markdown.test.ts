import { describe, expect, it } from "vitest";
import { escapeHtml, inlineMarkdownToHtml } from "./markdown";

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

  it("refuses dangerous link schemes, leaving them as plain text", () => {
    const out = inlineMarkdownToHtml("[click](javascript:alert(1))");
    expect(out).not.toContain("<a ");
    expect(out).toContain("[click]");
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
