<script lang="ts">
  // Filters the server-rendered timeline feed by toggling row visibility — the
  // rows (and their build-time diffs) stay in the Astro HTML; this island owns
  // the controls, the show/hide logic, and the monthly-mix chart, which is
  // re-counted against the current agency/portfolio/search slice so it always
  // charts the slice the feed is showing. Filter state round-trips through the
  // URL query string, so any filtered view is a shareable link. No-JS users see
  // the default view (content changes only) and the full-corpus chart.
  import MonthlyChart from "@/islands/MonthlyChart.svelte";
  import { formatMonth } from "@/lib/format";
  import { STACK_TIERS, type MonthlyMixRow, type StackTier } from "@/lib/monthly";
  import { READABLE_TIERS, type ChangeTier, type FieldSource } from "@/lib/profile-labels";
  import { SOURCE_GROUP_LABEL } from "@/lib/questions";

  interface AgencyOpt {
    abbr: string;
    name: string;
  }

  interface RequirementOpt {
    key: string;
    label: string;
    source: FieldSource;
    count: number;
  }

  let {
    agencies,
    portfolios,
    requirements,
    chart,
    total,
  }: {
    agencies: AgencyOpt[];
    portfolios: string[];
    requirements: RequirementOpt[];
    chart: MonthlyMixRow[];
    total: number;
  } = $props();

  // The questions a change touched, grouped by the instrument that asks them.
  const requirementGroups = $derived(
    (Object.keys(SOURCE_GROUP_LABEL) as FieldSource[])
      .map((source) => ({
        label: SOURCE_GROUP_LABEL[source],
        options: requirements.filter((r) => r.source === source),
      }))
      .filter((g) => g.options.length > 0),
  );

  const ANSWER_OPTIONS = [
    { value: "", label: "Any" },
    { value: "removed", label: "Dropped an answer" },
    { value: "added", label: "Added an answer" },
    { value: "changed", label: "Altered an answer" },
  ];
  const SCOPE_OPTIONS = [
    { value: "", label: "All bodies" },
    { value: "mandatory", label: "Bound by the policy" },
    { value: "voluntary", label: "Publishing voluntarily" },
    { value: "exempt", label: "Carved out of the policy" },
  ];

  // One control over the change-tier ladder: the default view is everything
  // that changed (or may have changed) what a statement says.
  const SHOW_OPTIONS = [
    { value: "read", label: "Changes worth reading" },
    { value: "substance", label: "Changes of substance" },
    { value: "revision", label: "Reworded, same substance" },
    { value: "cosmetic", label: "Cosmetic edits" },
    { value: "noise", label: "Noise" },
    { value: "first", label: "First tracked" },
    { value: "all", label: "Everything" },
  ];
  const showValues = new Set(SHOW_OPTIONS.map((o) => o.value));

  // Hydrate filter state from the query string; SSR renders the defaults.
  const params = typeof location === "undefined" ? null : new URLSearchParams(location.search);
  const urlShow = params?.get("show") ?? "";
  const urlMonth = params?.get("month") ?? "";

  let q = $state(params?.get("q") ?? "");
  let agency = $state(params?.get("agency") ?? "");
  let portfolio = $state(params?.get("portfolio") ?? "");
  const urlAbout = params?.get("about") ?? "";
  let about = $state(urlAbout);
  // A stale or mistyped ?about= filters nothing rather than hiding everything.
  const aboutKey = $derived(requirements.some((r) => r.key === about) ? about : "");
  const urlAnswers = params?.get("answers") ?? "";
  let answers = $state(ANSWER_OPTIONS.some((o) => o.value === urlAnswers) ? urlAnswers : "");
  const urlScope = params?.get("scope") ?? "";
  let scope = $state(SCOPE_OPTIONS.some((o) => o.value === urlScope) ? urlScope : "");
  let show = $state(showValues.has(urlShow) ? urlShow : "read");
  let month = $state<string | null>(/^\d{4}-\d{2}$/.test(urlMonth) ? urlMonth : null);
  // Counted from the DOM after hydration; falls back to `total` for SSR/no-JS.
  let shown: number | undefined = $state();
  // Recounted from the DOM each filter change; the build-time prop covers
  // SSR/no-JS.
  let live: MonthlyMixRow[] | null = $state(null);

  // Row text is cached lazily on the first search keystroke: reading the
  // textContent of every row (diffs included) once is cheap; per-keystroke is
  // then a string scan.
  let searchText: Map<HTMLElement, string> | null = null;

  // A row's facets are "requirement:direction" pairs, so "about" and "answers"
  // together match one answer that did both (a dropped commitment).
  function facetOk(facets: string): boolean {
    if (!aboutKey && !answers) return true;
    return facets.split(" ").some((f) => {
      const [req, dir] = f.split(":");
      return (!aboutKey || req === aboutKey) && (!answers || dir === answers);
    });
  }

  function syncUrl() {
    const p = new URLSearchParams();
    if (q.trim()) p.set("q", q.trim());
    if (agency) p.set("agency", agency);
    if (portfolio) p.set("portfolio", portfolio);
    if (scope) p.set("scope", scope);
    if (aboutKey) p.set("about", aboutKey);
    if (answers) p.set("answers", answers);
    if (show !== "read") p.set("show", show);
    if (month) p.set("month", month);
    const qs = p.toString();
    const url = qs ? `${location.pathname}?${qs}` : location.pathname;
    if (url !== `${location.pathname}${location.search}`) history.replaceState(null, "", url);
  }

  $effect(() => {
    const rows = document.querySelectorAll<HTMLElement>(".tl-row");
    const query = q.trim().toLowerCase();
    if (query && searchText === null) {
      searchText = new Map();
      for (const row of rows) searchText.set(row, row.textContent?.toLowerCase() ?? "");
    }
    const stackTiers = new Set<string>(STACK_TIERS);
    const byMonth = new Map<string, Record<StackTier, number>>();
    let count = 0;
    for (const row of rows) {
      const tier = (row.dataset.tier ?? "") as ChangeTier;
      const rowMonth = row.dataset.month ?? "";
      const sliceOk =
        (!agency || row.dataset.abbr === agency) &&
        (!portfolio || row.dataset.portfolio === portfolio) &&
        (!scope || row.dataset.scope === scope) &&
        facetOk(row.dataset.facets ?? "") &&
        (!query || (searchText?.get(row) ?? "").includes(query));
      const showOk = show === "all" || (show === "read" ? READABLE_TIERS.has(tier) : show === tier);
      const visible = sliceOk && showOk && (!month || rowMonth === month);
      if (row.hidden === visible) row.hidden = !visible;
      if (visible) count++;
      // The chart counts the slice, not the view: the tier and month controls
      // narrow the feed below it, never the overview.
      if (sliceOk && stackTiers.has(tier)) {
        let m = byMonth.get(rowMonth);
        if (!m) {
          m = { substance: 0, revision: 0, cosmetic: 0, noise: 0, unclassified: 0 };
          byMonth.set(rowMonth, m);
        }
        m[tier as StackTier]++;
      }
    }
    shown = count;
    live = chart.map(({ month: m }) => ({
      month: m,
      substance: 0,
      revision: 0,
      cosmetic: 0,
      noise: 0,
      unclassified: 0,
      ...byMonth.get(m),
    }));
    syncUrl();
  });
</script>

<div class="tl-explorer">
  <MonthlyChart data={live ?? chart} selected={month} onselect={(m) => (month = m)} />

  <div class="tl-filter">
    <label class="tl-filter__field tl-filter__search">
      <span>Search</span>
      <input type="search" placeholder="words in the summary or the change itself" bind:value={q} />
    </label>

    <label class="tl-filter__field">
      <span>Show</span>
      <select bind:value={show}>
        {#each SHOW_OPTIONS as o (o.value)}
          <option value={o.value}>{o.label}</option>
        {/each}
      </select>
    </label>

    <label class="tl-filter__field">
      <span>About</span>
      <select bind:value={about}>
        <option value="">Any question</option>
        {#each requirementGroups as g (g.label)}
          <optgroup label={g.label}>
            {#each g.options as r (r.key)}
              <option value={r.key}>{r.label} ({r.count})</option>
            {/each}
          </optgroup>
        {/each}
      </select>
    </label>

    <label class="tl-filter__field">
      <span>Answers</span>
      <select bind:value={answers}>
        {#each ANSWER_OPTIONS as o (o.value)}
          <option value={o.value}>{o.label}</option>
        {/each}
      </select>
    </label>

    <label class="tl-filter__field">
      <span>Agency</span>
      <select bind:value={agency}>
        <option value="">All agencies</option>
        {#each agencies as a (a.abbr)}
          <option value={a.abbr}>{a.name}</option>
        {/each}
      </select>
    </label>

    <label class="tl-filter__field">
      <span>Portfolio</span>
      <select bind:value={portfolio}>
        <option value="">All portfolios</option>
        {#each portfolios as p (p)}
          <option value={p}>{p}</option>
        {/each}
      </select>
    </label>

    <label class="tl-filter__field">
      <span>Coverage</span>
      <select bind:value={scope}>
        {#each SCOPE_OPTIONS as o (o.value)}
          <option value={o.value}>{o.label}</option>
        {/each}
      </select>
    </label>

    {#if month}
      <button type="button" class="tl-filter__month mono" onclick={() => (month = null)}>
        {formatMonth(month)}
        <span aria-hidden="true">&times;</span>
        <span class="visually-hidden">clear the month filter</span>
      </button>
    {/if}

    <span class="tl-filter__count mono" aria-live="polite">{shown ?? total} shown</span>
  </div>
</div>

<style>
  .tl-explorer {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  .tl-filter {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3) var(--space-4);
    padding: var(--space-3) var(--space-4);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  @media (width >= 48rem) {
    .tl-filter {
      position: sticky;
      top: 3.5rem;
      z-index: 5;
    }
  }

  .tl-filter__field {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 0.9rem;
    color: var(--muted);
  }

  .tl-filter__search {
    flex: 1 1 16rem;
  }

  input[type="search"] {
    flex: 1;
    min-width: 0;
    font: inherit;
    font-size: 0.9rem;
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
  }

  select {
    font: inherit;
    font-size: 0.9rem;
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
    max-width: 15rem;
  }

  .tl-filter__month {
    font-size: 0.85rem;
    padding: var(--space-1) var(--space-2);
    border: 1px solid var(--accent);
    border-radius: 999px;
    background: var(--accent-wash);
    color: var(--accent-ink);
    cursor: pointer;
  }

  .tl-filter__count {
    margin-inline-start: auto;
    color: var(--muted);
    font-size: 0.85rem;
  }
</style>
