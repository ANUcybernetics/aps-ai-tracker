<script lang="ts">
  // Stacked monthly bars of recorded changes by tier (substance / cosmetic /
  // noise), drawn at render time so the un-hydrated version (the home page
  // teaser) needs no JavaScript. The SVG carries only the marks, positioned in
  // percentages against a fixed-height plot, and every label is HTML overlaid
  // on top — so the type stays a constant size and the segment gaps stay 2px
  // whatever width the chart renders at. Pass `onselect` to make each month a
  // toggle (the timeline page's date filter): an invisible button per month
  // band carries focus, hover and pressed state. The <details> table is the
  // accessible reading of the same numbers.
  import { formatMonth, formatMonthLong } from "@/lib/format";
  import { STACK_TIERS, type MonthlyMixRow, type StackTier } from "@/lib/monthly";

  let {
    data,
    selected = null,
    onselect,
  }: {
    data: MonthlyMixRow[];
    selected?: string | null;
    onselect?: (month: string | null) => void;
  } = $props();

  const PLOT_H = 144; // px — keep in sync with .mmx__area block-size
  const GAP = (2 / PLOT_H) * 100; // 2px surface gap between stacked segments
  const CAP_R = 3; // rounded data-end on the top segment
  const CAP_PCT = (CAP_R / PLOT_H) * 100; // the same radius as a share of plot height
  const BAR_FRAC = 0.38; // bar thickness as a share of its month band

  const TIER_LABEL: Record<StackTier, string> = {
    substance: "changes of substance",
    revision: "revisions, same substance",
    cosmetic: "cosmetic edits",
    noise: "scrape noise",
    unclassified: "unclassified",
  };

  function niceMax(v: number): number {
    const p = 10 ** Math.floor(Math.log10(v));
    for (const m of [1, 2, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }

  let n = $derived(data.length);
  // Only tiers with any events anywhere get a series, a legend entry, and a
  // table column — a tier the corpus has never produced stays invisible until
  // the day it happens.
  let activeTiers = $derived(STACK_TIERS.filter((t) => data.some((d) => d[t] > 0)));
  let totals = $derived(data.map((d) => STACK_TIERS.reduce((sum, t) => sum + d[t], 0)));
  let yMax = $derived(niceMax(Math.max(...totals, 1)));
  let maxIdx = $derived(totals.indexOf(Math.max(...totals)));

  interface Seg {
    key: StackTier;
    label: string;
    value: number;
    top: number; // % from plot top
    h: number; // % of plot height
  }

  let columns = $derived(
    data.map((d, i) => {
      const x = ((i + (1 - BAR_FRAC) / 2) / n) * 100;
      const w = (BAR_FRAC / n) * 100;
      const centre = ((i + 0.5) / n) * 100;
      const segs: Seg[] = [];
      let cum = 0;
      for (const t of activeTiers) {
        const value = d[t];
        if (value === 0) continue;
        const h = (value / yMax) * 100 - (segs.length > 0 ? GAP : 0);
        cum += value;
        segs.push({
          key: t,
          label: TIER_LABEL[t],
          value,
          top: (1 - cum / yMax) * 100,
          h: Math.max(h, 0.75),
        });
      }
      return { month: d.month, x, w, centre, segs, total: cum };
    }),
  );

  let ticks = $derived(yMax >= 10 && yMax % 2 === 0 ? [0, yMax / 2, yMax] : [0, yMax]);
  // Sparse x labels: first, last, and the Januaries in between.
  let xLabels = $derived(
    data
      .map((d, i) => ({ month: d.month, i }))
      .filter(({ month, i }) => i === 0 || i === n - 1 || month.endsWith("-01")),
  );

  const DESCRIBE_LABEL: Record<StackTier, string> = {
    substance: "of substance",
    revision: "revisions",
    cosmetic: "cosmetic",
    noise: "scrape noise",
    unclassified: "unclassified",
  };

  function describe(d: MonthlyMixRow): string {
    const total = STACK_TIERS.reduce((sum, t) => sum + d[t], 0);
    const parts = activeTiers.map((t) => `${d[t]} ${DESCRIBE_LABEL[t]}`).join(", ");
    return `${formatMonthLong(d.month)}: ${total} ${total === 1 ? "change" : "changes"} — ${parts}`;
  }

  const uid = $props.id();
</script>

{#if n > 0}
  <figure class="mmx">
    <div class="mmx__plot">
      <div class="mmx__area">
        <svg role="img" aria-labelledby={`${uid}-title`} aria-describedby={`${uid}-desc`}>
          <title id={`${uid}-title`}>Recorded changes per month, stacked by tier</title>
          <desc id={`${uid}-desc`}>
            {describe(data[maxIdx])} was the busiest month. Figures in the table below.
          </desc>
          {#each ticks as t (t)}
            <line
              x1="0"
              x2="100%"
              y1={`${(1 - t / yMax) * 100}%`}
              y2={`${(1 - t / yMax) * 100}%`}
              class="mmx__grid"
            />
          {/each}
          {#each columns as col (col.month)}
            <g class="mmx__col" class:is-dimmed={selected !== null && selected !== col.month}>
              {#each col.segs as seg, k (seg.key)}
                <rect
                  x={`${col.x}%`}
                  y={`${seg.top}%`}
                  width={`${col.w}%`}
                  height={`${seg.h}%`}
                  rx={k === col.segs.length - 1 ? CAP_R : 0}
                  class={`mmx__seg mmx__seg--${seg.key}`}
                >
                  <title>{formatMonthLong(col.month)} — {seg.label}: {seg.value}</title>
                </rect>
                {#if k === col.segs.length - 1 && seg.h > 2 * CAP_PCT}
                  <!-- square off the rx'd bottom corners: the data-end rounds, the
                       baseline/gap edge stays square. Pure % maths is exact here
                       because the plot height is fixed. -->
                  <rect
                    x={`${col.x}%`}
                    y={`${seg.top + seg.h - CAP_PCT}%`}
                    width={`${col.w}%`}
                    height={`${CAP_PCT}%`}
                    class={`mmx__seg mmx__seg--${seg.key}`}
                  />
                {/if}
              {/each}
            </g>
          {/each}
        </svg>
        {#each ticks as t (t)}
          <span class="mmx__ytick mono" style={`top: ${(1 - t / yMax) * 100}%`}>{t}</span>
        {/each}
        {#each columns as col, i (col.month)}
          {#if i === maxIdx || col.month === selected}
            <span
              class="mmx__cap mono"
              class:is-dimmed={selected !== null && selected !== col.month}
              style={`left: ${col.centre}%; bottom: calc(${(col.total / yMax) * 100}% + 4px)`}
            >
              {col.total}
            </span>
          {/if}
        {/each}
        {#each xLabels as { month, i } (month)}
          <span
            class="mmx__xtick mono"
            class:is-first={i === 0}
            class:is-last={i === n - 1}
            style={i === 0
              ? "left: 0"
              : i === n - 1
                ? "right: 0"
                : `left: ${((i + 0.5) / n) * 100}%`}
          >
            {formatMonth(month)}
          </span>
        {/each}
        {#if onselect}
          <div class="mmx__hits">
            {#each data as d (d.month)}
              <button
                type="button"
                class="mmx__hit"
                aria-pressed={selected === d.month}
                title={describe(d)}
                aria-label={`${describe(d)}. ${selected === d.month ? "Clear the month filter." : "Show only this month."}`}
                onclick={() => onselect?.(selected === d.month ? null : d.month)}
              ></button>
            {/each}
          </div>
        {/if}
      </div>
    </div>
    <div class="mmx__legend">
      {#each activeTiers as t (t)}
        <span class="mmx__key"><i class={`mmx__swatch mmx__seg--${t}`}></i>{TIER_LABEL[t]}</span>
      {/each}
    </div>
    <details class="mmx__table">
      <summary>Figures</summary>
      <table>
        <thead>
          <tr>
            <th scope="col">Month</th>
            {#each activeTiers as t (t)}
              <th scope="col">{TIER_LABEL[t]}</th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each data as d (d.month)}
            <tr>
              <td>{formatMonth(d.month)}</td>
              {#each activeTiers as t (t)}
                <td>{d[t]}</td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </details>
  </figure>
{/if}

<style>
  .mmx {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    max-inline-size: 42rem;
  }

  /* Gutters host the overlaid HTML labels; the plot area itself is a fixed
     height so the 2px stack gaps and rounded caps stay true pixels. */
  .mmx__plot {
    padding-inline-start: 2.2rem;
    padding-block: 0.75rem 1.5rem;
  }

  .mmx__area {
    position: relative;
    block-size: 144px; /* keep in sync with PLOT_H */
  }

  svg {
    position: absolute;
    inset: 0;
    inline-size: 100%;
    block-size: 100%;
    display: block;
    overflow: visible;
  }

  .mmx__grid {
    stroke: var(--border);
    stroke-width: 1;
  }

  .mmx__col,
  .mmx__cap {
    transition: opacity var(--dur-fast) var(--ease-out-quart);
  }

  .mmx__col.is-dimmed,
  .mmx__cap.is-dimmed {
    opacity: 0.35;
  }

  .mmx__seg--substance {
    fill: var(--tier-substance);
    background: var(--tier-substance);
  }

  .mmx__seg--revision {
    fill: var(--tier-revision);
    background: var(--tier-revision);
  }

  .mmx__seg--cosmetic {
    fill: var(--tier-cosmetic);
    background: var(--tier-cosmetic);
  }

  .mmx__seg--noise {
    fill: var(--tier-noise);
    background: var(--tier-noise);
  }

  .mmx__seg--unclassified {
    fill: var(--tier-unclassified);
    background: var(--tier-unclassified);
  }

  .mmx__ytick,
  .mmx__xtick,
  .mmx__cap {
    position: absolute;
    font-size: 0.7rem;
    color: var(--muted);
    line-height: 1;
    pointer-events: none;
  }

  .mmx__ytick {
    inset-inline-start: -0.5rem;
    transform: translate(-100%, -50%);
  }

  .mmx__xtick {
    inset-block-start: calc(100% + 0.4rem);
    transform: translateX(-50%);
  }

  .mmx__xtick.is-first,
  .mmx__xtick.is-last {
    transform: none;
  }

  /* At phone widths the first/last labels are enough; the in-between Januaries
     collide with them. */
  @media (width < 30rem) {
    .mmx__xtick:not(.is-first, .is-last) {
      display: none;
    }
  }

  .mmx__cap {
    color: var(--text);
    transform: translateX(-50%);
  }

  /* One invisible button per month band, over the plot. */
  .mmx__hits {
    position: absolute;
    inset: 0;
    display: flex;
  }

  .mmx__hit {
    flex: 1;
    border: 0;
    padding: 0;
    background: transparent;
    cursor: pointer;
    border-radius: var(--radius-sm);
  }

  .mmx__hit:hover {
    background: oklch(0% 0 0 / 4%);
  }

  .mmx__hit:focus-visible {
    outline: 2px solid var(--accent-ink);
    outline-offset: 1px;
  }

  .mmx__legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
    font-size: var(--text-xs);
    color: var(--muted);
  }

  .mmx__key {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
  }

  .mmx__swatch {
    inline-size: 10px;
    block-size: 10px;
    border-radius: 2px;
  }

  .mmx__table summary {
    cursor: pointer;
    font-size: var(--text-xs);
    color: var(--muted);
    width: max-content;
  }

  .mmx__table table {
    margin-block-start: var(--space-2);
    font-size: var(--text-xs);
    border-collapse: collapse;
    font-variant-numeric: tabular-nums;
  }

  .mmx__table th,
  .mmx__table td {
    text-align: start;
    padding: 0.15rem 0.6rem 0.15rem 0;
    border-block-end: 1px solid var(--border);
  }
</style>
