<script lang="ts">
  import type { PassageCluster } from "@/types/exporter";
  import { statementPath, dataUrl, withBase } from "@/lib/paths";
  import { formatDate } from "@/lib/format";
  import { inlineMarkdownToHtml } from "@/lib/markdown";

  // Full agency names keyed by abbreviation, so the member pills and the
  // first-observed link can name the acronym on hover.
  let { names = {} }: { names?: Record<string, string> } = $props();

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
    <ul class="pb__skeleton" aria-hidden="true">
      {#each Array(6) as _, i (i)}
        <li>
          <span class="pb__sk-line pb__sk-meta"></span>
          <span class="pb__sk-line"></span>
          <span class="pb__sk-line pb__sk-short"></span>
        </li>
      {/each}
    </ul>
    <p class="visually-hidden">Loading shared passages…</p>
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
          <!-- eslint-disable-next-line svelte/no-at-html-tags -- escaped + scheme-checked in inlineMarkdownToHtml -->
          <p class="pb__text">{@html inlineMarkdownToHtml(c.canonicalText)}</p>
          {#if c.firstObserved}
            <p class="pb__first">
              {#if c.firstObserved.abbr}
                <span class="muted">First observed:</span>
                <a
                  href={statementPath(c.firstObserved.abbr)}
                  title={names[c.firstObserved.abbr] ?? c.firstObserved.abbr}
                >{c.firstObserved.abbr}</a>,
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
                <a class="pill" href={statementPath(a)} title={names[a] ?? a}>{a}</a>
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

  /* Links rendered from the passage Markdown: ink with an ochre underline, like
     body links, but constrained so a long URL-y label still wraps. */
  .pb__text :global(a) {
    color: var(--text);
    text-decoration: underline;
    text-decoration-color: var(--accent);
    overflow-wrap: anywhere;
  }

  .pb__text :global(a):hover {
    color: var(--accent-ink);
  }

  .pb__text :global(code) {
    font-family: var(--font-mono);
    font-size: 0.85em;
  }

  /* Loading skeleton: stand-ins shaped like the real cluster rows so the section
     has weight before the data lands, instead of a bare line of text. */
  .pb__skeleton {
    list-style: none;
    margin: 0;
    padding: 0;
    border-block-start: 1px solid var(--border);
  }

  .pb__skeleton li {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-block: var(--space-4);
    border-block-end: 1px solid var(--border);
  }

  .pb__sk-line {
    block-size: 0.8rem;
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    inline-size: 100%;
  }

  .pb__sk-meta {
    inline-size: 8rem;
    block-size: 1rem;
  }

  .pb__sk-short {
    inline-size: 60%;
  }

  @media (prefers-reduced-motion: no-preference) {
    .pb__sk-line {
      animation: pb-shimmer 1.2s var(--ease-out-quart) infinite alternate;
    }
  }

  @keyframes pb-shimmer {
    from {
      opacity: 0.5;
    }
    to {
      opacity: 1;
    }
  }
</style>
