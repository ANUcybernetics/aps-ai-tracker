---
id: TASK-6
title: Data-viz pages render at ~25% scale in headless screenshots
status: Done
assignee: []
created_date: '2026-06-25 08:04'
updated_date: '2026-06-25 08:15'
labels:
  - rendering
  - site
dependencies: []
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The /propagation and /similarity pages render at roughly 25% scale when captured with a headless-Chromium viewport screenshot (e.g. agent-browser), even though page metrics are normal: innerWidth 1440, devicePixelRatio 1, body scrollWidth ~1425, no CSS zoom or transform on html/body. /overview and /timeline screenshot correctly at full scale in the same session. Per-element screenshots (e.g. screenshotting a section or div.graph) come out at natural resolution, so the content itself is fine -- it is something about how these two pages lay out for a full-viewport capture. Likely a client-side island (the Svelte similarity graph, the propagation leaderboard) that briefly forces a very large layout box the screenshot then scales to fit. Low priority -- discovered while grabbing figures for the ANU CV NTRO plate; worked around with element screenshots.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Root cause of the headless full-viewport scaling on /propagation and /similarity identified
- [x] #2 Both pages produce a correctly-scaled full-viewport screenshot, or the cause is documented as out-of-scope
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Not reproducible with current tooling (agent-browser 0.30.1); the captured PNGs are correct 1:1 viewport screenshots. No code change made.

## Investigation

Reproduced the reported setup against both the dev server and a production `pnpm build` + `pnpm preview`, capturing /similarity and /propagation with `agent-browser screenshot` (and `--full`).

DOM metrics are normal (matching the report): innerWidth 1440, devicePixelRatio 1, visualViewport scale 1, h1 width 1136px / font 52.8px, no zoom/transform. The SVG on /similarity measures 1134x600 (correct viewBox).

The screenshot files themselves are objectively correct, not scaled:
- Every capture is exactly 1440x1024 (viewport) or 1425x1247 (`--full`, matching scrollHeight) — never a 4x region.
- Pixel-level content bounding box fills the whole frame (0,0 → 1440,1024) on all pages, including the first /similarity grab — content is not squished into a corner.
- Full-res crops of the heading band show the h1 on /similarity and /propagation rendered at *identical* pixel size to /timeline (which uses client:load and "works"). Side-by-side: scratchpad/compare.png.

## Most likely explanation for the original "~25% scale" impression

A downscaled-preview illusion, not a render/capture bug. A full 1440-wide PNG shown shrunk in a viewer renders the 52px h1 at ~13px ("~25%"). /timeline and /overview survive this because their content is large text that stays legible when shrunk; /similarity (a fine scatter of node dots + tiny labels) and /propagation (a dense leaderboard) become illegible, reading as "scaled". Per-element screenshots (e.g. `div.graph`) produce a *smaller* image shown closer to 1:1, so they look crisp — matching the report.

The shared trait of the two affected pages is `client:visible` islands (SimilarityGraph, PassageBrowser) vs /timeline's `client:load`, but that affects hydration timing, not capture scale, and racing the capture immediately after navigation still produced a correct 1:1 image.

## If it recurs

The full-viewport PNG is correct at 1:1 even when a preview shrinks it — open the file at native resolution, or keep using element/region screenshots for the dense viz. If a genuinely scaled capture ever appears, grab the raw PNG dimensions and the bbox first; that distinguishes a real capture bug from the preview illusion.
<!-- SECTION:NOTES:END -->
