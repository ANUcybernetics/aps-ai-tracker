import {
  diff_match_patch,
  DIFF_DELETE,
  DIFF_EQUAL,
  DIFF_INSERT,
  type Diff,
} from "diff-match-patch";

// Relative so vitest resolves it without the `@/` alias (same as the tests).
import { escapeHtml } from "./markdown";

// Character-level diff with semantic cleanup: diff_cleanupSemantic coalesces the
// incidental short matches ("the", "AI", spaces) that a raw word-level diff pins
// as "unchanged", so a rewritten paragraph renders as one clean removal followed
// by one clean addition instead of interleaved word soup. Computed at build time
// so the client only ever ships <ins>/<del> markup, never a diff library.
function semanticDiff(before: string, after: string): Diff[] {
  const dmp = new diff_match_patch();
  const diffs = dmp.diff_main(before, after);
  dmp.diff_cleanupSemantic(diffs);
  return diffs;
}

function changeHtml(op: number, text: string): string {
  if (op === DIFF_INSERT) return `<ins>${text}</ins>`;
  if (op === DIFF_DELETE) return `<del>${text}</del>`;
  return text;
}

// The homepage is a digest of what agencies *said*, rather than every URL their
// CMS happened to emit. Replace inline-link destinations with an empty target
// while preserving the label and all other Markdown. This deliberately does not
// classify the revision as scrape noise: the full timeline and statement history
// still retain the event and its exact URL diff.
function withoutLinkDestinations(markdown: string): string {
  return markdown
    .replaceAll(/^\s*(?:[-*+]\s+)?!?\[[^\]]*\]\((?:[^()\\]|\\.|\([^)]*\))*\)\s*$/gm, "")
    .replaceAll(/(!?)\[([^\]]*)\]\((?:[^()\\]|\\.|\([^)]*\))*\)/g, "$1[$2]()")
    .replaceAll(/^(\s*\[[^\]]+\]:)\s*\S+.*$/gm, "$1")
    .replaceAll(/\s+/g, " ")
    .trim();
}

/** Whether a revision changes anything besides link targets or standalone links. */
export function hasStatementTextChange(before: string, after: string): boolean {
  return withoutLinkDestinations(before) !== withoutLinkDestinations(after);
}

// Full diff rendered to HTML. Used for revision time-travel.
export function wordDiffHtml(before: string, after: string): string {
  return semanticDiff(before, after)
    .map(([op, value]) => changeHtml(op, escapeHtml(value)))
    .join("");
}

// Compact variant for the timeline feed: keeps every change in full but elides
// long unchanged runs to ~`ctx` chars of surrounding context, so a 428-event
// page doesn't ship hundreds of whole statement bodies.
export function compactWordDiffHtml(before: string, after: string, ctx = 70): string {
  const diffs = semanticDiff(before, after);
  return diffs
    .map(([op, value], i) => {
      if (op !== DIFF_EQUAL) return changeHtml(op, escapeHtml(value));
      if (value.length <= ctx * 2 + 5) return escapeHtml(value);
      const head = escapeHtml(value.slice(0, ctx));
      const tail = escapeHtml(value.slice(-ctx));
      if (i === 0) return `&hellip; ${tail}`;
      if (i === diffs.length - 1) return `${head} &hellip;`;
      return `${head} &hellip; ${tail}`;
    })
    .join("");
}
