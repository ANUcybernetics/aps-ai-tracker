---
title: "A clearer tracker"
date: 2026-09-23
summary: "Every change on the site is now explained the same way, you can filter by the
  questions you'd actually ask, and every capture is checked and read by Claude
  Opus 5.5."
draft: true
---

The tracker has had a rework. The data underneath hasn't changed (every version
of every Australian Government AI transparency statement since November 2025),
but the site is better at saying what that data shows.

The main change is one explanation of what a "change" is. Each new capture of a
statement is read twice: once for how much the text changed, and once for which
of the statement's answers changed, filed under the question in the DTA
Standard, policy v2.0 or the APS AI Plan that it answers. The
[anatomy of a change](/reading#anatomy) sets this out, and the rest of the site
now uses its terms.

You can also filter by the questions you'd bring to the data. The timeline can
show just the
[commitments dropped between versions](/timeline?about=commitments&answers=removed),
and the agencies page can list
[every statement that says a Chief AI Officer is in place](/agencies?question=caio).
The old "policy in practice" page is now [what the statements say](/policy), and
it describes the text rather than the agencies: a statement that doesn't mention
a use-case register may still come from an agency that has one.

Underneath, every capture is now checked to be the statement at all before
anything reads it. That caught a few pages we'd been tracking that only linked
to the statement (IP Australia's, for almost five months) and one firewall block
page. The whole history has also been re-read with Claude Opus 5.5, and the
numbers moved a little, mostly because it reads "complies with legislation" more
strictly.

The [data downloads](/data/) have everything behind the site. If you spot
something wrong,
[open an issue](https://github.com/ANUcybernetics/aps-ai-tracker/issues).
