// All Markdown → HTML rendering for the site, as one hardened build-time
// pipeline (marked never ships to the client: passages arrive pre-rendered,
// via StatementBody at build or the passages.json endpoint).
//
// Scraped markdown is treated as untrusted everywhere: raw HTML is escaped
// rather than passed through, link URLs are scheme-checked, and images render
// as an alt-text placeholder (hotlinking an agency's image URL would show
// today's image in a historical revision, which is misleading).
import { Marked, type Token } from "marked";

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => ESCAPES[ch]!);
}

// Allow only links a public document would legitimately use; anything else
// (notably javascript:) renders as its label text rather than a link.
export function isSafeUrl(url: string): boolean {
  if (/^(https?:|mailto:)/i.test(url)) return true;
  // Relative, root-relative or fragment links are fine; a bare "scheme:" is not.
  return /^[/#.]/.test(url) || !/^[a-z][a-z0-9+.-]*:/i.test(url);
}

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

// Render the inline slice of Markdown (links, emphasis, code) that survives in
// a stored passage.
export function inlineMarkdownToHtml(text: string): string {
  return marked.parseInline(text, { async: false });
}

// Strip the leading block-level Markdown scaffolding that prefixes a stored
// passage — heading hashes, blockquote markers, list bullets — so a heading or
// quoted passage reads as text rather than showing "## …" or "> …" raw.
export function stripBlockMarkers(text: string): string {
  return text
    .replace(/^>\s?/gm, "") // blockquote marker on each line
    .replace(/^\s*(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+)/, "") // one leading heading/list marker
    .trim();
}

// Render a stored passage to safe display HTML: block scaffolding removed, then
// inline links/emphasis rendered.
export function passageToHtml(text: string): string {
  return inlineMarkdownToHtml(stripBlockMarkers(text));
}

// Render a full historical revision body for the statement page's revision
// time-travel, demoting headings so the shallowest becomes <h2> under the page
// <h1> (matching StatementBody's normalisation for the current revision).
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
