<script lang="ts">
  // Filters the server-rendered table of published statements by a reader's
  // question ("who say a Chief AI Officer is in place?"). Each row carries the
  // keys of the questions it answers yes to (questions.ts decides them at build
  // time); this island only toggles row visibility and keeps the choice in the
  // URL, so a filtered view is a shareable link. No-JS users see every row.
  interface Question {
    key: string;
    label: string;
    count: number;
  }

  let { questions, total }: { questions: Question[]; total: number } = $props();

  const params = typeof location === "undefined" ? null : new URLSearchParams(location.search);
  let question = $state(params?.get("question") ?? "");
  // A stale or mistyped ?question= filters nothing rather than hiding every row.
  const active = $derived(questions.some((q) => q.key === question) ? question : "");
  let shown: number | undefined = $state();

  $effect(() => {
    let count = 0;
    for (const row of document.querySelectorAll<HTMLElement>("tr[data-answers]")) {
      const visible = !active || (row.dataset.answers ?? "").split(" ").includes(active);
      if (row.hidden === visible) row.hidden = !visible;
      if (visible) count++;
    }
    shown = count;
    const url = active ? `${location.pathname}?question=${active}` : location.pathname;
    if (url !== `${location.pathname}${location.search}`) history.replaceState(null, "", url);
  });
</script>

<div class="aq">
  <label class="aq__field">
    <span>Show statements that</span>
    <select bind:value={question}>
      <option value="">(all published statements)</option>
      {#each questions as q (q.key)}
        <option value={q.key}>{q.label} ({q.count})</option>
      {/each}
    </select>
  </label>
  <span class="aq__count mono" aria-live="polite">{shown ?? total} shown</span>
</div>

<style>
  .aq {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3) var(--space-4);
    padding: var(--space-3) var(--space-4);
    margin-block-end: var(--space-3);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  .aq__field {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    font-size: 0.9rem;
    color: var(--muted);
  }

  .aq__field select {
    max-inline-size: 100%;
    font: inherit;
    font-size: 0.9rem;
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--text);
  }

  .aq__count {
    margin-inline-start: auto;
    font-size: var(--text-sm);
    color: var(--muted);
  }
</style>
