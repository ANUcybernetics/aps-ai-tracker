// Per-statement documents, loaded eagerly at build time. These carry full
// revision bodies, so import this module only from pages that render statement
// detail (the statement pages and the timeline's build-time diffs).
import type { StatementDoc } from "@/types/exporter";

const modules = import.meta.glob<{ default: StatementDoc }>("../generated/statements/*.json", {
  eager: true,
});

export const statements: Record<string, StatementDoc> = {};
for (const mod of Object.values(modules)) {
  statements[mod.default.abbr] = mod.default;
}

export const allStatements = Object.values(statements).toSorted((a, b) =>
  a.abbr.localeCompare(b.abbr),
);

export function getStatement(abbr: string): StatementDoc | undefined {
  return statements[abbr];
}
