---
title: "A clearer tracker"
date: 2026-09-23
summary:
  "Changes now have consistent explanations and question filters. Each saved
  page is also checked before it enters the archive."
draft: true
---

We've changed how the site explains its data. The archive still starts in
November 2025, but the timeline, statement pages and charts now use the same
terms for the changes they show.

When a statement changes, the tracker classifies the edit and compares the
answers in the new version with the previous one. Those answers are filed under
questions from the DTA Standard, policy v2.0 and the APS AI Plan.
[Reading the data](/reading#anatomy) explains both readings.

You can filter the timeline to show
[commitments dropped between versions](/timeline?about=commitments&answers=removed),
or use the agencies page to find
[every statement that says a Chief AI Officer is in place](/agencies?question=caio).
The old "policy in practice" page is now [what the statements say](/policy), and
it reports what the text says about agencies' practices. A statement's silence
about a use-case register does not establish that the agency lacks one.

Each captured page is now checked before it enters the archive. That caught
pages we'd been tracking that only linked to the statement (IP Australia's, for
almost five months) and one firewall block page. Some agencies publish their
statement as one section of a longer reporting page; we now capture only that
section, so an edit to a gifts register no longer appears as an AI statement
change. We also re-read the archive with Claude Opus 5.5.

The [data downloads](/data/) have everything behind the site. If you spot
something wrong,
[open an issue](https://github.com/ANUcybernetics/aps-ai-tracker/issues).
