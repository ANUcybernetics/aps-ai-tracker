<script lang="ts">
  import type { PassageCluster } from "@/types/exporter";
  import { statementPath, dataUrl, withBase } from "@/lib/paths";
  import { formatDate } from "@/lib/format";

  // Short gloss for a first-observed tier (see the Reading page for the full
  // explanation); the "tied" case is handled separately in the markup.
  function tierLabel(tier: string): string {
    if (tier === "added") return "added during tracking";
    if (tier === "present-at-start") return "present when tracking began";
    return "";
  }

  let clusters = $state<PassageCluster[]>([]);
  let status = $state<"loading" | "empty" | "ready">("loading");
  let query = $state("");
  let onlyDta = $state(false);

  // Fetch the (largish) cluster list rather than inlining it into the page HTML.
  $effect(() => {
    void (async () => {
      const data: { clusters: PassageCluster[] } = await (
        await fetch(dataUrl("passages.json"))
      ).json();
      clusters = data.clusters ?? [];
      status = clusters.length ? "ready" : "empty";
    })();
  });

  const filtered = $derived(
    clusters
      .filter((c) => !onlyDta || c.alsoInDta)
      .filter(
        (c) =>
          query.trim() === "" || c.canonicalText.toLowerCase().includes(query.trim().toLowerCase()),
      )
      .slice(0, 150),
  );
</script>

<div class="pb">
  {#if status === "loading"}
    <p class="muted">Loading shared passages…</p>
  {:else if status === "empty"}
    <p class="muted">No shared passages have been computed yet.</p>
  {:else}
    <div class="pb__controls">
      <input type="search" placeholder="Search shared text…" bind:value={query} />
      <label>
        <input type="checkbox" bind:checked={onlyDta} /> Only DTA-template passages
      </label>
      <span class="pb__count mono">{filtered.length} shown</span>
    </div>

    <ul class="pb__list">
      {#each filtered as c (c.normKey)}
        <li class="pb__cluster">
          <div class="pb__meta">
            <span class="pill">{c.count} agencies</span>
            {#if c.alsoInDta}<span class="pill pill--pdf">in DTA template</span>{/if}
            <span class="muted">{c.kind}</span>
          </div>
          <p class="pb__text">{c.canonicalText}</p>
          {#if c.firstObserved}
            <p class="pb__first">
              {#if c.firstObserved.abbr}
                <span class="muted">First observed:</span>
                <a href={statementPath(c.firstObserved.abbr)}>{c.firstObserved.abbr}</a>,
                {formatDate(c.firstObserved.date)}{#if tierLabel(c.firstObserved.tier)}
                  <span class="muted">· {tierLabel(c.firstObserved.tier)}</span>{/if}
              {:else}
                <span class="muted">Present across agencies from the corpus start</span>
              {/if}
              <a class="pb__how" href={withBase("/reading#first-observed")}>
                How to read this &rarr;
              </a>
            </p>
          {/if}
          <details class="pb__members">
            <summary>Which agencies</summary>
            <div class="cluster">
              {#each c.memberAbbrs as a (a)}
                <a class="pill" href={statementPath(a)}>{a}</a>
              {/each}
            </div>
          </details>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .pb__controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3) var(--space-5);
    margin-block-end: var(--space-4);
  }

  input[type="search"] {
    font: inherit;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
    min-width: 16rem;
    flex: 1;
  }

  label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 0.9rem;
  }

  .pb__count {
    color: var(--muted);
    font-size: 0.85rem;
  }

  .pb__list {
    list-style: none;
    margin: 0;
    padding: 0;
    border-block-start: 1px solid var(--border);
  }

  /* a divided results list reads lighter than 150 bordered cards */
  .pb__cluster {
    padding-block: var(--space-4);
    border-block-end: 1px solid var(--border);
  }

  .pb__meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin-block-end: var(--space-2);
  }

  .pb__text {
    margin: 0;
    font-size: 0.95rem;
    color: var(--text);
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .pb__first {
    margin: var(--space-2) 0 0;
    font-size: 0.85rem;
  }

  .pb__first a {
    color: var(--accent);
    text-decoration: none;
  }

  .pb__first a:hover {
    text-decoration: underline;
  }

  .pb__how {
    margin-inline-start: var(--space-2);
    white-space: nowrap;
  }

  .pb__members {
    margin-block-start: var(--space-3);
  }

  .pb__members summary {
    cursor: pointer;
    color: var(--muted);
    font-size: 0.85rem;
    width: max-content;
  }

  .pb__members .cluster {
    margin-block-start: var(--space-2);
  }

  .pb__members a.pill {
    text-decoration: none;
    color: var(--accent);
  }
</style>
