# Design

Visual system for the AI Tracker site (`site/`). Strategy lives in
[PRODUCT.md](PRODUCT.md); this captures how it looks. Tokens are defined in
`site/src/styles/tokens.css` and applied in `site/src/styles/global.css`.

## Overview

A public register that reads the government's AI homework with a highlighter.
Ink on cool paper, one confident ochre signature, a civic newspaper-masthead
voice. The design is editorial data-journalism, not a dashboard: bold headlines,
dramatised figures, and visualisations that all speak one language.

**The unifying idea:** warm ochre = borrowed / templated / reused; ink = bespoke
(an agency's own words). This single semantic runs through the passage-reuse
heat-map, the agency "register wall", the originality bars, and the similarity
graph, so a reader learns it once and reads it everywhere.

Light and dark are both first-class, via `color-scheme` + `light-dark()`.

## Color

OKLCH throughout, defined as light/dark pairs. Strategy: **committed** — ochre
carries the brand and the data encoding; everything else is ink, paper, and the
conventional diff green/red.

| Role | Token | Light | Dark |
| --- | --- | --- | --- |
| Paper (bg) | `--bg` | `oklch(98.6% 0.003 250)` | `oklch(17.5% 0.014 264)` |
| Surface | `--surface` | `oklch(96.8% 0.004 250)` | `oklch(20.5% 0.016 264)` |
| Surface 2 | `--surface-2` | `oklch(93.8% 0.006 250)` | `oklch(24.5% 0.018 264)` |
| Ink (text) | `--text` | `oklch(23% 0.024 264)` | `oklch(92% 0.012 250)` |
| Muted | `--muted` | `oklch(45% 0.022 264)` | `oklch(67% 0.016 250)` |
| Border | `--border` | `oklch(88% 0.008 255)` | `oklch(30% 0.016 264)` |
| Border strong | `--border-strong` | `oklch(74% 0.012 255)` | `oklch(42% 0.018 264)` |
| Ochre (fills, marks) | `--accent` | `oklch(66% 0.142 64)` | `oklch(80% 0.14 78)` |
| Ochre (text/links) | `--accent-ink` | `oklch(46% 0.132 54)` | `oklch(83% 0.13 80)` |
| Ochre wash | `--accent-wash` | `oklch(95% 0.04 78)` | `oklch(27% 0.05 70)` |

Plus a 4-step warm **heat ramp** (`--heat-1`…`--heat-4`, faint yellow → deep
amber) for reuse intensity, conventional **diff** colours (`--ins-*` green,
`--del-*` red), and `--ok` green for positive deltas. The similarity graph
encodes originality on a hardcoded ochre → neutral → teal scale (mid-lightness
so nodes read on both canvases) in `SimilarityGraph.svelte`.

**Contrast:** every text/background pair clears WCAG AA in both schemes,
including ink on every heat step (≥6.3:1) and ochre links (≥7:1). Verified by
rendering the real tokens through a canvas and computing ratios.

## Typography

Two families, hierarchy from width + weight rather than a font zoo.

- **Archivo Variable** (`--font-sans`) — display and body. A grotesque built for
  editorial use; pushed wide + heavy (`font-stretch` 86–112%, weight 700–800)
  for masthead headlines, normal for body. Self-hosted via
  `@fontsource-variable/archivo/standard.css` (carries both `wght` and `wdth`).
- **JetBrains Mono Variable** (`--font-mono`) — the ledger texture: dates, commit
  SHAs, byte deltas, key figures, labels. Mono is earned here (the project runs
  on git), not costume.

Fluid modular scale (`--text-xs` … `--display`, clamp()ed, ≈1.25–1.3 ratio).
Display ceiling 4.75rem. Headlines are condensed-heavy with tight tracking and
`text-wrap: balance`; prose uses `text-wrap: pretty` and a 66ch measure.

## Spacing & layout

Spacing scale `--space-1` … `--space-12` plus a fluid `--space-section`
(2.75–5rem) for the rhythm between major page sections. Crisp, document-like
radii (`--radius` 6px, `--radius-sm` 3px). Page max 74rem, gutters via `.page`.
Layouts favour rules and dividers over boxes; cards are used sparingly.

## Components

- **Masthead** (`Nav.astro`): sticky, lightly blurred, expanded-Archivo wordmark
  with the ochre "Tracker", ochre underline on the active nav item.
- **Register wall** (`AgencyWall.astro`): one cell per agency, coloured by
  templated-ness (ochre) or bespoke (ink); gaps and exemptions read as absences.
  The lead figure on the home and agencies pages; the agencies table is the
  accessible canonical list.
- **Coverage** (`CoverageStats.astro`): a sentence-led headline figure + a
  semantic facts list. Deliberately not a row of identical stat cards.
- **Directory** (home Explore): editorial link rows (title + mono data hint +
  sliding arrow), not an identical-card grid.
- **Editorial links**: ink text with an ochre marker underline; colour is never
  the only signal.
- **Bars** (originality, leaderboard): ink fill (own words) on an ochre track
  (borrowed remainder), so each bar reads itself.
- **Heat / pills / diff**: highlighter spans for passage reuse; pills for status
  (noise reads as a de-emphasised dashed pill, not an alarm); green/red diffs.

## Motion

Easing via `--ease-out-quart` / `--ease-out-expo`; durations `--dur-fast` …
`--dur-slow`. One orchestrated entrance on the home (dateline → headline → lede →
wall rise, staggered) rather than fade-on-scroll everywhere. Hover
micro-interactions: feed-row tint, directory-arrow slide, wall-cell lift.
Cross-document view transitions for navigation. Every animation is gated on
`prefers-reduced-motion: no-preference` and collapses to instant under reduce.

## Accessibility

WCAG 2.2 AA. AA contrast everywhere (measured), semantic HTML and headings, a
skip link, visible `:focus-visible` rings (ochre-ink, ≥3:1), reduced-motion
fallbacks, and meaning never carried by colour alone (heat, diff, status, and
graph encodings all pair colour with text, shape, or a labelled table).
