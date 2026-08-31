// Bucket timeline events into calendar months (Canberra time) stacked by change
// tier, for the monthly-mix chart on the home and timeline pages. First-tracked
// captures are imports into the corpus, not changes, so they are excluded from
// the stacks; their months still appear (zero-filled) so the axis is honest
// about when tracking was active.
import { DISPLAY_TIME_ZONE } from "@/lib/format";
import { changeTier } from "@/lib/profile-labels";
import type { ChangeKind } from "@/types/exporter";

export interface MonthlyMixRow {
  month: string; // "YYYY-MM"
  substance: number;
  cosmetic: number;
  noise: number;
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
    const tier = changeTier(event.changeKind);
    if (tier === "first") continue;
    let row = byMonth.get(month);
    if (!row) {
      row = { month, substance: 0, cosmetic: 0, noise: 0 };
      byMonth.set(month, row);
    }
    if (tier === "content") row.substance++;
    else if (tier === "cosmetic") row.cosmetic++;
    else row.noise++;
  }
  const rows: MonthlyMixRow[] = [];
  for (let m = first as string; m <= (last as string); m = nextMonth(m)) {
    rows.push(byMonth.get(m) ?? { month: m, substance: 0, cosmetic: 0, noise: 0 });
  }
  return rows;
}
