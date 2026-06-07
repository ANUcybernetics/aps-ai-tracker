// Centralised base-aware URL construction. The site is served from a non-root
// base on GitHub Pages (/aps-ai-transparency-tracker/), so EVERY internal link,
// asset and island fetch must go through here — a raw "/timeline" works in
// `astro dev` but 404s in production.

const BASE = import.meta.env.BASE_URL; // Astro guarantees a trailing slash.

export function withBase(path: string): string {
  const trimmed = path.startsWith("/") ? path.slice(1) : path;
  return BASE.endsWith("/") ? BASE + trimmed : `${BASE}/${trimmed}`;
}

export function statementPath(abbr: string): string {
  return withBase(`/statements/${abbr}`);
}

export function dataUrl(file: string): string {
  return withBase(`/data/${file}`);
}
