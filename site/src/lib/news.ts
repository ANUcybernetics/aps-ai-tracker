// News posts: the helpers the Bluesky announcer shares with its tests. The
// site itself reads posts through the `news` content collection; the
// announcer runs outside Astro, so it reads the same files with this small
// parser. News frontmatter is deliberately flat (title, date, summary, draft),
// which is all the parser handles, plus the indented continuation lines the
// markdown formatter folds a long value onto.
import type { Ledger } from "@/lib/atproto";

export interface NewsPost {
  slug: string;
  title: string;
  date: string; // YYYY-MM-DD
  summary: string;
  draft: boolean;
}

/** Parse a news post's flat YAML frontmatter; throws on anything missing. */
export function parseNewsPost(slug: string, text: string): NewsPost {
  const match = /^---\n([\s\S]*?)\n---\n/.exec(text);
  if (!match) throw new Error(`${slug}: no frontmatter`);
  const raw: Record<string, string> = {};
  let last: string | undefined;
  for (const line of match[1]!.split("\n")) {
    const kv = /^(\w+):\s*(.*)$/.exec(line);
    if (kv) {
      last = kv[1]!;
      raw[last] = kv[2]!;
    } else if (last && /^\s+\S/.test(line)) {
      raw[last] = `${raw[last]} ${line.trim()}`.trim();
    }
  }
  const fields = Object.fromEntries(
    Object.entries(raw).map(([k, v]) => [k, v.replace(/^(["'])([\s\S]*)\1$/, "$2")]),
  );
  for (const key of ["title", "date", "summary"]) {
    if (!fields[key]) throw new Error(`${slug}: frontmatter needs ${key}`);
  }
  return {
    slug,
    title: fields.title!,
    date: fields.date!,
    summary: fields.summary!,
    draft: fields.draft === "true",
  };
}

export const newsLedgerKey = (slug: string) => `news:${slug}`;

/** Published posts not yet announced, oldest first. Drafts never qualify. */
export function newsToAnnounce(posts: NewsPost[], ledger: Ledger): NewsPost[] {
  return posts
    .filter((p) => !p.draft && !(newsLedgerKey(p.slug) in ledger))
    .toSorted((a, b) => a.date.localeCompare(b.date) || a.slug.localeCompare(b.slug));
}

/** The skeet text: the title and summary, inside Bluesky's 300-grapheme cap. */
export function newsPostText(post: NewsPost): string {
  const text = `${post.title}\n\n${post.summary}`;
  const graphemes = [...new Intl.Segmenter("en", { granularity: "grapheme" }).segment(text)];
  if (graphemes.length <= 300) return text;
  return `${graphemes
    .slice(0, 299)
    .map((g) => g.segment)
    .join("")
    .trimEnd()}…`;
}
