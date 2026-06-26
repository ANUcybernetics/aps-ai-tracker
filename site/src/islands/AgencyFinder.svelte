<script lang="ts">
  // A labelled search box that live-filters the full agency list by name or
  // abbreviation. Published agencies link straight to their statement; not-yet
  // and exempt agencies still surface (so a search never looks "empty" for a
  // real agency) but read as muted, non-clickable rows with their status.
  //
  // Navigational results, not a forced combobox: each match is a real link, so
  // Tab walks them natively. ArrowDown from the input drops into the list for
  // keyboard users; a polite live region announces the running count.
  import { statementPath } from "@/lib/paths";

  interface Finder {
    abbr: string;
    name: string;
    status: "published" | "not-yet" | "exempt";
  }

  let {
    agencies,
    label = "Find an agency",
    placeholder = "Search by name or abbreviation…",
  }: { agencies: Finder[]; label?: string; placeholder?: string } = $props();

  const STATUS_NOTE: Record<Finder["status"], string> = {
    published: "",
    "not-yet": "not yet published",
    exempt: "exempt",
  };

  let query = $state("");

  // Rank prefix matches (on abbr or name) above mid-string ones, so typing
  // "ABS" or "Aus" lands the obvious answer at the top; ties keep name order.
  const matches = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const scored = [];
    for (const a of agencies) {
      const name = a.name.toLowerCase();
      const abbr = a.abbr.toLowerCase();
      let rank: number;
      if (abbr === q || name === q) rank = 0;
      else if (abbr.startsWith(q) || name.startsWith(q)) rank = 1;
      else if (abbr.includes(q) || name.includes(q)) rank = 2;
      else continue;
      scored.push({ a, rank });
    }
    return scored.sort((x, y) => x.rank - y.rank).map((s) => s.a);
  });

  let listEl = $state<HTMLUListElement>();

  // ArrowDown from the input hands focus to the first result link.
  function onInputKeydown(e: KeyboardEvent) {
    if (e.key === "ArrowDown" && matches.length) {
      e.preventDefault();
      listEl?.querySelector<HTMLAnchorElement>("a")?.focus();
    } else if (e.key === "Escape") {
      query = "";
    }
  }

  // Arrow keys roam the result links; Escape returns to the input.
  function onListKeydown(e: KeyboardEvent) {
    const links = [...(listEl?.querySelectorAll<HTMLAnchorElement>("a") ?? [])];
    const i = links.indexOf(document.activeElement as HTMLAnchorElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      links[Math.min(i + 1, links.length - 1)]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (i <= 0) inputEl?.focus();
      else links[i - 1]?.focus();
    } else if (e.key === "Escape") {
      query = "";
      inputEl?.focus();
    }
  }

  let inputEl = $state<HTMLInputElement>();
</script>

<div class="finder">
  <label class="finder__label" for="agency-finder">{label}</label>
  <input
    bind:this={inputEl}
    bind:value={query}
    onkeydown={onInputKeydown}
    id="agency-finder"
    type="search"
    {placeholder}
    autocomplete="off"
    role="combobox"
    aria-expanded={matches.length > 0}
    aria-controls="agency-finder-results"
  />

  <p class="visually-hidden" aria-live="polite">
    {query.trim() === ""
      ? ""
      : matches.length === 0
        ? "No agencies match"
        : `${matches.length} ${matches.length === 1 ? "agency" : "agencies"} match`}
  </p>

  {#if query.trim() !== ""}
    {#if matches.length === 0}
      <p class="finder__empty">No agency matches “{query.trim()}”.</p>
    {:else}
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <ul
        class="finder__results"
        id="agency-finder-results"
        bind:this={listEl}
        onkeydown={onListKeydown}
      >
        {#each matches as a (a.abbr)}
          <li class="finder__row" data-status={a.status}>
            {#if a.status === "published"}
              <a class="finder__hit" href={statementPath(a.abbr)}>
                <span class="finder__name">{a.name}</span>
                <span class="finder__abbr mono">{a.abbr}</span>
              </a>
            {:else}
              <span class="finder__hit finder__hit--muted">
                <span class="finder__name">{a.name}</span>
                <span class="finder__abbr mono">{a.abbr}</span>
                <span class="finder__note">{STATUS_NOTE[a.status]}</span>
              </span>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</div>

<style>
  .finder {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .finder__label {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--accent-ink);
    letter-spacing: 0.01em;
  }

  input[type="search"] {
    font: inherit;
    padding: var(--space-3) var(--space-4);
    border-radius: var(--radius);
    border: 1px solid var(--border-strong);
    background: var(--bg);
    color: var(--text);
    width: 100%;
    max-width: 34rem;
    transition:
      border-color var(--dur-fast) var(--ease-out-quart),
      box-shadow var(--dur-fast) var(--ease-out-quart);
  }

  input[type="search"]:focus-visible {
    outline: none;
    border-color: var(--accent-ink);
    box-shadow: 0 0 0 3px color-mix(in oklab, var(--accent) 28%, transparent);
  }

  .finder__empty {
    margin: 0;
    max-width: 34rem;
    color: var(--muted);
    font-size: 0.95rem;
  }

  .finder__results {
    list-style: none;
    margin: 0;
    padding: 0;
    max-width: 34rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    overflow: clip;
    max-height: 22rem;
    overflow-y: auto;
  }

  .finder__row + .finder__row {
    border-block-start: 1px solid var(--border);
  }

  .finder__hit {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    text-decoration: none;
    color: var(--text);
  }

  a.finder__hit {
    transition: background var(--dur-fast) var(--ease-out-quart);
  }

  a.finder__hit:hover,
  a.finder__hit:focus-visible {
    background: color-mix(in oklab, var(--accent) 12%, var(--surface));
    outline: none;
  }

  a.finder__hit:hover .finder__name,
  a.finder__hit:focus-visible .finder__name {
    color: var(--accent-ink);
  }

  .finder__hit--muted {
    color: var(--muted);
  }

  .finder__name {
    font-weight: 600;
  }

  .finder__hit--muted .finder__name {
    font-weight: 500;
  }

  .finder__abbr {
    font-size: var(--text-sm);
    color: var(--muted);
    letter-spacing: 0.02em;
  }

  .finder__note {
    margin-inline-start: auto;
    font-size: var(--text-xs);
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
</style>
