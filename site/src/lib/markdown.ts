// Render the small slice of inline Markdown that survives in scraped passage
// text — links and basic emphasis — to safe HTML. Shared passages are stored as
// normalised Markdown, so without this the browser shows raw `[label](url)`
// syntax, which reads as broken formatting to a newcomer.
//
// This is deliberately tiny rather than pulling `marked` into the client bundle:
// passages only ever contain links, bold, italic and inline code. Everything is
// HTML-escaped first and link URLs are scheme-checked, so the result is safe to
// inject with Svelte's {@html}.

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
// (notably javascript:) renders as plain bracketed text rather than a link.
function isSafeUrl(url: string): boolean {
  if (/^(https?:|mailto:)/i.test(url)) return true;
  // Relative, root-relative or fragment links are fine; a bare "scheme:" is not.
  return /^[/#.]/.test(url) || !/^[a-z][a-z0-9+.-]*:/i.test(url);
}

// Null byte: can't occur in the source text, so it's a collision-proof sentinel
// for protecting code spans from later passes.
const NUL = String.fromCharCode(0);

export function inlineMarkdownToHtml(text: string): string {
  let html = escapeHtml(text);

  // Pull inline code out into placeholders first, so link/emphasis markers
  // inside it stay literal and aren't reprocessed; spliced back in at the end.
  const code: string[] = [];
  html = html.replace(/`([^`]+)`/g, (_m, inner: string) => {
    code.push(`<code>${inner}</code>`);
    return `${NUL}${code.length - 1}${NUL}`;
  });

  // Links: [label](url). The label may itself carry emphasis, handled below.
  html = html.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    (whole, label: string, url: string) =>
      isSafeUrl(url)
        ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
        : whole,
  );

  // Emphasis. Bold before italic so ** isn't eaten as two single *.
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  html = html.replace(/(^|[^\w])_([^_\n]+)_(?=[^\w]|$)/g, "$1<em>$2</em>");

  // Restore the protected code spans.
  html = html.replace(
    new RegExp(`${NUL}(\\d+)${NUL}`, "g"),
    (_m, i: string) => code[Number(i)]!,
  );

  return html;
}
