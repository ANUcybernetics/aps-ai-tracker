---
id: TASK-8
title: Review the September 2026 redesign and pipeline hardening
status: To Do
assignee: []
created_date: '2026-09-23 09:30'
labels:
  - review
  - site
  - pipeline
dependencies: []
priority: high
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
A long session (commits ba5c28b..HEAD, 23 Sep 2026) reworked the site copy and structure and hardened the scraping pipeline. It was built and checked incrementally but never reviewed as a whole. Review it with fresh context before the first news post goes out.

What landed:
- copy sweep for AI tropes across every page, then an 'anatomy of a change' on /reading that the rest of the site now points at
- /policy renamed 'What the statements say', with neutral 'says, not does' wording throughout
- change tiers (noise, cosmetic, reworded, substantive) shown in place of the finer kinds; delta 'significance' removed
- profile fields filed under the requirement they answer (REQUIREMENTS in site/src/lib/profile-labels.ts)
- question filters on /timeline (about, answers, coverage, starters) and /agencies (AgencyQuestions); logic in site/src/lib/questions.ts
- nav cut to six items; propagation, who's who and data moved to the footer
- news section (site/src/content/news, /news, /news.xml) with Bluesky announcement through atproto-publish --crosspost; first post a-clearer-tracker.md is still draft: true
- pipeline: WAF block pages rejected on the httpx path; capture_check.py (Opus 5.5 verdict on every capture, cached in .cache/captures.json, rejected captures dropped like a quarantine); model-judged noise revisions now re-read their profile; default model Opus 5.5 and the whole history re-read with it; URL fixes for IPA, ASIO, DVSC; ACCC hand-captured past an Akamai block

Known loose ends to check:
- the Opus 5.5 re-read made the Standard checklist stricter (mandatory statements with all eight elements went from 51 to 43; 'compliance with legislation' flipped for 8, e.g. OAIC, ALRC, FWO, APSC)
- IGIS's page carries non-AI accountability content, and a change to its legal-services text (17 Sep) was classed substantive; other statements that share a page with non-AI content may do the same
- profile-delta removals rose from 124 to 182, likely many reworded commitments matched as dropped and re-added
- the cron's new steps (committing .cache/captures.json, nb todos for rejected captures) have not yet run for real
- ACCC's nightly fetch fails against Akamai; decide whether it becomes manual = true
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Every page's copy has been read end to end for accuracy, AI tropes and the 'says, not does' rule, and anything wrong is fixed
- [ ] #2 A sample of at least 20 capture-check verdicts (rejections and borderline acceptances) has been checked against the captured text, with any false verdict confirmed or quarantined in captures.toml
- [ ] #3 The Opus 5.5 Standard-element shifts have been spot-checked, and the site's figures are either confirmed or corrected
- [ ] #4 Non-AI page content being classed as a substantive change (the IGIS case) is either fixed or recorded as a known limitation on /reading
- [ ] #5 The dropped-commitment lists on /policy and the timeline have been spot-checked for reworded commitments shown as dropped, with the finding either fixed or explained on /reading
- [ ] #6 The timeline and agencies filters give correct results for each starter question and each agency question, on desktop and at phone width
- [ ] #7 At least one nightly run has completed with the new cron steps, the captures cache is committed, and any rejected-capture todos are sensible
- [ ] #8 ACCC is either fetching again or marked manual = true with a manual_reason
- [ ] #9 The first news post has been edited and published (draft: false), and its Bluesky announcement has gone out once
<!-- AC:END -->
