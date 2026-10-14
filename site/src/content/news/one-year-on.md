---
title: "One year on: from “we don't use AI” to “a human makes the decision”"
date: 2026-11-11
summary:
  "In a year of archived AI transparency statements, 21 agencies deleted a
  sentence saying they didn't use AI. Most now promise that a human makes the
  decision, and few say how that is checked."
draft: true
---

Since February 2025, most Australian Government agencies have had to publish an
[AI transparency statement](https://www.digital.gov.au/ai/ai-in-government-policy/standard-ai-transparency-statements):
a public web page saying how the agency uses AI.[^scope] The tracker has checked
every one of them daily since 11 November 2025 and kept each version, so anyone
can see what an agency changed and when.

A year on it holds 431 versions of 121 statements. Most versions are of no
interest, being site redesigns, bot blocks, and fixes to formatting or links.
That leaves 128 changes of substance from 84 agencies, and reading those diffs
turned up three patterns. A statement is what an agency chooses to say about its
AI use, so none of them means an agency has done anything wrong.

First, 21 agencies deleted a sentence saying they didn't use AI somewhere: in
their services, with the public, or in administration.
[Sport Integrity Australia](/statements/SIA) made the change in May. Its
statement used to say:

> Currently, we do not use AI in any services or advice we provide externally
> (publicly) or internally.

It now says:

> Currently, SIA does not use AI systems to independently provide public
> services, make regulatory decisions, or deliver advice without human review
> and accountability mechanisms.

The new sentence permits AI anywhere a person reviews the result. Six other
agencies made the same move, and the rest went three different ways.

<figure class="split">
  <div class="split__bar" role="img" aria-label="Of the 21 agencies, 7 now say not without a person, 5 gave a narrower no, 4 say they use AI and 5 put nothing in the sentence's place.">
    <span class="split__seg split__seg--accent" style="flex-grow: 7">7</span>
    <span class="split__seg split__seg--ochre" style="flex-grow: 5">5</span>
    <span class="split__seg split__seg--ink" style="flex-grow: 4">4</span>
    <span class="split__seg split__seg--grey" style="flex-grow: 5">5</span>
  </div>
  <figcaption>
    What 21 agencies put in place of “we don't use AI”: 7 wrote “not without a
    person”, 5 a narrower “no”, 4 “we use AI”, and 5 nothing.
  </figcaption>
</figure>

Some of the narrower versions are easy to miss. In June [ACMA](/statements/ACMA)
replaced "ACMA does not plan to use AI in services that the public may directly
interact with or be significantly impacted by" with "ACMA does not currently
deploy AI in direct interactions with the public". The new sentence makes no
claim about plans, and it no longer covers AI that affects the public without
interacting with them. Others reversed the sentence outright: in March
[DEWR](/statements/DEWR) went from "does not currently use AI in service
delivery" to "uses AI to support service delivery". In April
[Safe Work Australia](/statements/SWA) deleted "We do not propose to use AI
where the public may directly interact with or be significantly impacted by it"
and put nothing in its place.

Second, nine agencies disclosed a new use of AI in the lead-up to a decision.
The [Commonwealth Ombudsman](/statements/OCO)'s is the easiest to picture. When
someone complains about a government agency, AI writes "a short summary", which
the Office uses "to help us find the right team and staff member" and "to help
us prioritise the most urgent complaints". A person decides what happens next,
and the statement says the summaries "are never used to make a decision about
what action to take in relation to a complaint". The other eight:

- [Veterans' Affairs](/statements/DVA) is piloting a claims document reader that
  "does not make decisions or determine claim outcomes"
- the [Fair Work Commission](/statements/FWC) sorts enterprise agreements for
  staff to consider
- [DCCEEW](/statements/DCCEEW) is trialling AI in recruitment, alongside a human
  selection panel
- the [NDIS Commission](/statements/NDISQSC) annotates complaints and incident
  reports
- the [Taxation Ombudsman](/statements/IGTO) summarises complaint cases
- the [ATO](/statements/ATO) alerts taxpayers to lodgments suspected of identity
  crime
- [Education](/statements/EDUCATION) flags anomalies for staff to review
- the [DTA](/statements/DTA), which sets the standard for these statements, has
  AI assess applications to its Digital Marketplace panel and make
  recommendations to a human decision maker

Third, the promise of human oversight is now in 92 of the 121 statements, and 36
of those 92 name no way of checking it. A check here means any mention of
testing or evaluation, audit or assurance, or a way to report an incident or
raise a concern.

<figure class="split">
  <div class="split__bar" role="img" aria-label="Of 121 statements, 36 promise human oversight and name no check, 56 promise it and name at least one check, and 29 make no such promise.">
    <span class="split__seg split__seg--ink" style="flex-grow: 36">36</span>
    <span class="split__seg split__seg--accent" style="flex-grow: 56">56</span>
    <span class="split__seg split__seg--hollow" style="flex-grow: 29">29</span>
  </div>
  <figcaption>
    All 121 statements: 36 promise human oversight and name no way of checking
    it, 56 promise it and name at least one check, and 29 make no such promise.
  </figcaption>
</figure>

Knowing that a person makes the decision doesn't tell you whether they catch the
mistakes in an AI summary of a complaint. Testing and audit are how an agency
would find out. Other commitments have gone over the same year. Nine agencies
dropped their promise to review the statement annually; the
[National Blood Authority](/statements/NBA) replaced it with "We will update
this transparency statement if our approach changes". Eight dropped or weakened
a claim to comply with the policy or a standard, and
[Finance](/statements/FINANCE) went from "has implemented all mandatory
requirements" to "is committed to the full implementation of the Policy". The
timeline can filter for
[commitments dropped between versions](/timeline?about=commitments&answers=removed).

Everything behind this post is in the [data downloads](/data/): the answers each
statement gives (CSV and JSON), the timeline of changes, and
[the text of every version](https://github.com/ANUcybernetics/aps-ai-tracker/tree/main/statements)
in git. It is all CC BY 4.0. One warning from doing this analysis: every change
of substance has a model-written summary, and counting keywords in those
summaries gave wrong answers. That first pass found 24 agencies deleting a "we
don't use AI" sentence, 35 moving a trial into everyday use, and 12 dropping
their annual review. Reading the diffs cut those to 21, 13 and 9. Two of the
dropped reviews, the DTA's among them, were sentences our own scraper had lost
and later restored. Use the summaries to find a change, then read the diff.

There are questions in the data that we haven't followed up:

- thirteen agencies moved AI from a trial into everyday use (Austrade "has since
  made Copilot available to all staff"); which of them say what the trial found?
- six loosened their rules for staff, and the Taxation Ombudsman now allows
  "publicly available AI tools in low-risk situations"; are the rest heading the
  same way?
- are the 36 statements that promise oversight without a check from small
  agencies with little AI, or large ones?
- much of the wording is [shared between agencies](/propagation); when one
  agency edits a shared sentence, do the others follow?

If you find an answer, or spot something we got wrong,
[open an issue](https://github.com/ANUcybernetics/aps-ai-tracker/issues).

[^scope]:
    The
    [policy for the responsible use of AI in government](https://www.digital.gov.au/policy/ai/policy)
    binds non-corporate Commonwealth entities and carves out the defence
    portfolio and the national intelligence community. The 121 statements
    include some from corporate entities that publish voluntarily.
