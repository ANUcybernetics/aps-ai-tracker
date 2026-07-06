// Render a full historical revision body (Markdown from the exporter) to HTML
// at build time, for the statement page's revision time-travel. The current
// revision renders through StatementBody with passage heat; historical bodies
// have no passage annotations, so they render as plain prose here.
//
// marked runs only at build time — the client ships static HTML. Scraped
// markdown is treated as untrusted: raw HTML is escaped rather than passed
// through, link URLs go through the same scheme check as passage links, and
// images render as an alt-text placeholder (hotlinking an agency's image URL
// would show today's image in a historical revision, which is misleading).
import { Marked, type Token } from "marked";

import { escapeHtml, isSafeUrl } from "./markdown";

const marked = new Marked({ gfm: true });

marked.use({
  renderer: {
    html({ text }) {
      return escapeHtml(text);
    },
    image({ text }) {
      const alt = text.trim();
      return alt ? `<em class="rev-img">[image: ${escapeHtml(alt)}]</em>` : "";
    },
    link({ href, tokens }) {
      const inner = this.parser.parseInline(tokens);
      if (!isSafeUrl(href)) return inner;
      return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${inner}</a>`;
    },
  },
});

// Demote headings so the shallowest becomes <h2> under the page <h1>, matching
// StatementBody's normalisation for the current revision.
export function revisionBodyToHtml(md: string): string {
  const tokens: Token[] = marked.lexer(md);
  const depths: number[] = [];
  for (const t of tokens) {
    if (t.type === "heading") depths.push(t.depth);
  }
  const offset = depths.length ? 2 - Math.min(...depths) : 0;
  if (offset !== 0) {
    for (const t of tokens) {
      if (t.type === "heading") t.depth = Math.min(Math.max(t.depth + offset, 2), 6);
    }
  }
  return marked.parser(tokens);
}
