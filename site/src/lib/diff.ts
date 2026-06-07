import { diffWordsWithSpace } from "diff";

const ESCAPE: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
};

function escapeHtml(text: string): string {
  return text.replace(/[&<>]/g, (c) => ESCAPE[c]);
}

// Word-level diff rendered to HTML at build time, so the client never ships a
// diff library — only <ins>/<del> markup. Used for revision time-travel.
export function wordDiffHtml(before: string, after: string): string {
  return diffWordsWithSpace(before, after)
    .map((part) => {
      const text = escapeHtml(part.value);
      if (part.added) return `<ins>${text}</ins>`;
      if (part.removed) return `<del>${text}</del>`;
      return text;
    })
    .join("");
}

// Compact variant for the timeline feed: keeps every change in full but elides
// long unchanged runs to ~`ctx` chars of surrounding context, so a 428-event
// page doesn't ship hundreds of whole statement bodies.
export function compactWordDiffHtml(before: string, after: string, ctx = 70): string {
  const parts = diffWordsWithSpace(before, after);
  return parts
    .map((part, i) => {
      const text = escapeHtml(part.value);
      if (part.added) return `<ins>${text}</ins>`;
      if (part.removed) return `<del>${text}</del>`;
      if (part.value.length <= ctx * 2 + 5) return text;
      const head = escapeHtml(part.value.slice(0, ctx));
      const tail = escapeHtml(part.value.slice(-ctx));
      if (i === 0) return `&hellip; ${tail}`;
      if (i === parts.length - 1) return `${head} &hellip;`;
      return `${head} &hellip; ${tail}`;
    })
    .join("");
}
