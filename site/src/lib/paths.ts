// Centralised base-aware URL construction. The site is served from the root of
// the apsaitracker.app custom domain, but EVERY internal link, asset and island
// fetch still goes through here so links stay correct if the base ever changes.

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
