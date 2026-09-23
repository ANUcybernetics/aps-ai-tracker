import { describe, expect, it } from "vitest";
import { newsLedgerKey, newsPostText, newsToAnnounce, parseNewsPost } from "./news";

const post = (slug: string, date: string, draft = false) => ({
  slug,
  title: `Post ${slug}`,
  date,
  summary: "A summary.",
  draft,
});

describe("parseNewsPost", () => {
  it("reads flat frontmatter, quoted or not", () => {
    const text = `---\ntitle: "A new look"\ndate: 2026-09-24\nsummary: What changed.\ndraft: true\n---\n\nBody.`;
    expect(parseNewsPost("a-new-look", text)).toEqual({
      slug: "a-new-look",
      title: "A new look",
      date: "2026-09-24",
      summary: "What changed.",
      draft: true,
    });
  });

  it("joins a value the formatter folded onto indented lines", () => {
    const text = `---\ntitle: T\ndate: 2026-09-24\nsummary:\n  "The first line, and\n  the second."\n---\n`;
    expect(parseNewsPost("t", text).summary).toBe("The first line, and the second.");
  });

  it("treats a missing draft flag as published", () => {
    const text = `---\ntitle: T\ndate: 2026-09-24\nsummary: S\n---\n`;
    expect(parseNewsPost("t", text).draft).toBe(false);
  });

  it("refuses a post without a summary", () => {
    expect(() => parseNewsPost("t", `---\ntitle: T\ndate: 2026-09-24\n---\n`)).toThrow(/summary/);
  });
});

describe("newsToAnnounce", () => {
  it("skips drafts and posts already in the ledger, oldest first", () => {
    const posts = [post("c", "2026-10-02"), post("a", "2026-09-24"), post("d", "2026-10-03", true)];
    const ledger = { [newsLedgerKey("b")]: { seeded: true as const } };
    posts.push(post("b", "2026-09-30"));
    expect(newsToAnnounce(posts, ledger).map((p) => p.slug)).toEqual(["a", "c"]);
  });
});

describe("newsPostText", () => {
  it("fits Bluesky's 300-grapheme limit", () => {
    const long = { ...post("x", "2026-09-24"), summary: "word ".repeat(100) };
    const text = newsPostText(long);
    const graphemes = [...new Intl.Segmenter("en", { granularity: "grapheme" }).segment(text)];
    expect(graphemes.length).toBeLessThanOrEqual(300);
    expect(text.endsWith("…")).toBe(true);
  });
});
