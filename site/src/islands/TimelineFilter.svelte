<script lang="ts">
  // Filters the server-rendered timeline feed by toggling row visibility — the
  // rows (and their build-time diffs) stay in the Astro HTML; this island only
  // owns the controls and the show/hide logic. No-JS users see the full feed.
  interface AgencyOpt {
    abbr: string;
    name: string;
  }

  let { agencies, total }: { agencies: AgencyOpt[]; total: number } = $props();

  let agency = $state("");
  let showTracked = $state(false);
  let showNoise = $state(false);
  // Counted from the DOM after hydration; falls back to `total` for SSR/no-JS.
  let shown: number | undefined = $state();

  $effect(() => {
    const rows = document.querySelectorAll<HTMLElement>(".tl-row");
    let count = 0;
    for (const row of rows) {
      const matchesAgency = !agency || row.dataset.abbr === agency;
      const trackedOk = row.dataset.kind !== "tracked-since" || showTracked;
      const noiseOk = row.dataset.noise !== "true" || showNoise;
      const visible = matchesAgency && trackedOk && noiseOk;
      row.hidden = !visible;
      if (visible) count++;
    }
    shown = count;
  });
</script>

<div class="tl-filter">
  <label class="tl-filter__field">
    <span>Agency</span>
    <select bind:value={agency}>
      <option value="">All agencies</option>
      {#each agencies as a (a.abbr)}
        <option value={a.abbr}>{a.name}</option>
      {/each}
    </select>
  </label>

  <label class="tl-filter__toggle">
    <input type="checkbox" bind:checked={showTracked} />
    Show first-tracked
  </label>

  <label class="tl-filter__toggle">
    <input type="checkbox" bind:checked={showNoise} />
    Show noise
  </label>

  <span class="tl-filter__count mono">{shown ?? total} shown</span>
</div>

<style>
  .tl-filter {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3) var(--space-5);
    padding: var(--space-3) var(--space-4);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    position: sticky;
    top: 3.5rem;
    z-index: 5;
  }

  .tl-filter__field {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 0.9rem;
    color: var(--muted);
  }

  select {
    font: inherit;
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
    max-width: 18rem;
  }

  .tl-filter__toggle {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 0.9rem;
  }

  .tl-filter__count {
    margin-inline-start: auto;
    color: var(--muted);
    font-size: 0.85rem;
  }
</style>
