---
id: TASK-6
title: Data-viz pages render at ~25% scale in headless screenshots
status: To Do
assignee: []
created_date: '2026-06-25 08:04'
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
- [ ] #1 Root cause of the headless full-viewport scaling on /propagation and /similarity identified
- [ ] #2 Both pages produce a correctly-scaled full-viewport screenshot, or the cause is documented as out-of-scope
<!-- AC:END -->
