// The timeline's diffs ship as one static file instead of inside the page,
// which would otherwise carry every diff behind a closed <details>. The file
// is fetched once, the first time a reader opens a diff or searches the feed.
import { withBase } from "@/lib/paths";

export const TIMELINE_DIFFS_PATH = "/timeline/diffs.json";

// One key per timeline event: a scrape commit touches many statements, so the
// sha alone isn't unique.
export function diffKey(abbr: string, sha: string): string {
  return `${abbr}/${sha}`;
}

let pending: Promise<Record<string, string>> | null = null;

export function loadTimelineDiffs(): Promise<Record<string, string>> {
  pending ??= fetch(withBase(TIMELINE_DIFFS_PATH)).then((res) => {
    if (!res.ok) throw new Error(`${TIMELINE_DIFFS_PATH}: ${res.status}`);
    return res.json() as Promise<Record<string, string>>;
  });
  // A failed fetch mustn't stick: the next open or keystroke tries again.
  pending.catch(() => {
    pending = null;
  });
  return pending;
}
