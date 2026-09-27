import type { APIRoute } from "astro";
import { compactWordDiffHtml } from "@/lib/diff";
import { getTimeline } from "@/lib/load";
import { getStatements } from "@/lib/statements";
import { diffKey } from "@/lib/timeline-diffs";
import { revisionPair } from "@/lib/timeline-revisions";

// The rendered diff for every timeline event that has one, keyed by
// diffKey(), which the timeline page fetches on demand (see
// lib/timeline-diffs.ts).
export const GET: APIRoute = async () => {
  const timeline = await getTimeline();
  const statements = await getStatements();
  const diffs: Record<string, string> = {};
  for (const event of timeline) {
    const pair = revisionPair(statements, event);
    if (pair)
      diffs[diffKey(event.abbr, event.sha)] = compactWordDiffHtml(pair.prev.body, pair.curr.body);
  }
  return new Response(JSON.stringify(diffs), { headers: { "content-type": "application/json" } });
};
