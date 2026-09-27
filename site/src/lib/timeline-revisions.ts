// Joins a timeline event to its statement's revision history, for the
// timeline page and the diffs file it loads on demand.
import type { StatementDoc, TimelineEvent } from "@/types/exporter";

export function revisionFor(statements: Record<string, StatementDoc>, event: TimelineEvent) {
  const stmt = statements[event.statementId];
  const idx = stmt ? stmt.timeline.findIndex((t) => t.sha === event.sha) : -1;
  return idx < 0 ? null : { stmt, idx };
}

// The event's revision and the one before it; null for a first-seen event,
// which has nothing to diff against.
export function revisionPair(statements: Record<string, StatementDoc>, event: TimelineEvent) {
  const found = revisionFor(statements, event);
  if (!found || found.idx === 0) return null;
  return { prev: found.stmt.timeline[found.idx - 1], curr: found.stmt.timeline[found.idx] };
}
