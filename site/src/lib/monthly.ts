// Bucket timeline events into calendar months (Canberra time) stacked by change
// tier, for the monthly-mix chart on the home and timeline pages. First-tracked
// captures are imports into the corpus, not changes, so they are excluded from
// the stacks; their months still appear (zero-filled) so the axis is honest
// about when tracking was active.
import { DISPLAY_TIME_ZONE } from "@/lib/format";
import { changeTier, type ChangeTier } from "@/lib/profile-labels";
import type { ChangeKind } from "@/types/exporter";

// Stacking order, baseline up: the story series (substance) sits on the axis.
export const STACK_TIERS = ["substance", "revision", "cosmetic", "noise", "unclassified"] as const;
export type StackTier = (typeof STACK_TIERS)[number];

export type MonthlyMixRow = { month: string } & Record<StackTier, number>;

function emptyRow(month: string): MonthlyMixRow {
  return { month, substance: 0, revision: 0, cosmetic: 0, noise: 0, unclassified: 0 };
}

const MONTH_KEY = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  timeZone: DISPLAY_TIME_ZONE,
});

// The Canberra calendar month of an event timestamp, as "YYYY-MM". Slicing the
// ISO string would misfile boundary events stamped in another zone (a 31 Jul
// UTC evening is 1 Aug in Canberra).
export function monthKey(iso: string): string {
  return MONTH_KEY.format(new Date(iso));
}

function nextMonth(month: string): string {
  const y = Number(month.slice(0, 4));
  const m = Number(month.slice(5, 7));
  return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`;
}

export function monthlyMix(events: { date: string; changeKind: ChangeKind }[]): MonthlyMixRow[] {
  if (events.length === 0) return [];
  const byMonth = new Map<string, MonthlyMixRow>();
  let first: string | null = null;
  let last: string | null = null;
  for (const event of events) {
    const month = monthKey(event.date);
    if (first === null || month < first) first = month;
    if (last === null || month > last) last = month;
    const tier: ChangeTier = changeTier(event.changeKind);
    if (tier === "first") continue;
    let row = byMonth.get(month);
    if (!row) {
      row = emptyRow(month);
      byMonth.set(month, row);
    }
    row[tier]++;
  }
  const rows: MonthlyMixRow[] = [];
  for (let m = first as string; m <= (last as string); m = nextMonth(m)) {
    rows.push(byMonth.get(m) ?? emptyRow(m));
  }
  return rows;
}
