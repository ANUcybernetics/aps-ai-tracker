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
