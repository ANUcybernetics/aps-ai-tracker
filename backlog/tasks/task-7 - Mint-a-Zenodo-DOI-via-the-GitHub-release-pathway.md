---
id: TASK-7
title: Mint a Zenodo DOI via the GitHub release pathway
status: To Do
assignee: []
created_date: '2026-06-25 08:11'
labels:
  - zenodo
  - doi
dependencies: []
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Give the tracker a citable DOI for the ANU promotion NTRO plate (and citation generally), using the Zenodo GitHub-release integration (already enabled for this repo) rather than a manual/API mint.

Rationale: a DOI must resolve to a frozen, archived artefact. The release pathway archives a real, reproducible snapshot of the code plus the scraped corpus at that instant -- which matches the tracker's whole 'version-controlled faithful record' premise and lets anyone pull exactly the data behind the analyses. The integration stays dormant until a release is published (daily cron commits don't trigger it), so there's no DOI spam and nothing to maintain. Don't also API-mint the same work, or you get two unrelated Zenodo records.

Mechanics to remember: the DOI is minted on a published GitHub Release, NOT by the presence of a metadata file. Metadata precedence is .zenodo.json > CITATION.cff > LICENSE > repo/release info; if both .zenodo.json and CITATION.cff exist the .cff is ignored, so use one. CITATION.cff also gives GitHub's 'Cite this repository' widget. You can't preview/reserve the DOI before the release.

Order of operations: add CITATION.cff at repo root (title; Ben Swift sole author + ORCID; description; type: software; MIT; repo URL) -> publish one deliberate tagged release (e.g. v2026.06; cut more only when a new citable snapshot is wanted) -> read the minted DOI off the Zenodo record -> use the CONCEPT ('all versions') DOI, since the tracker is a living daily-rescraped artefact -> paste it into the benswift-cv.typ APS AI Transparency Tracker plate (the doi: TODO, promotion repo TASK-37 AC#1) and rebuild.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 CITATION.cff added at repo root with correct metadata (sole author, ORCID, type: software, MIT, repo URL)
- [ ] #2 One tagged GitHub release published and the Zenodo integration has minted a DOI
- [ ] #3 Concept (all-versions) DOI recorded and handed to promotion repo TASK-37 AC#1
<!-- AC:END -->
