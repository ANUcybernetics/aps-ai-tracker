---
id: TASK-7
title: Mint a Zenodo DOI via the GitHub release pathway
status: Done
assignee: []
created_date: '2026-06-25 08:11'
updated_date: '2026-06-25 08:24'
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
- [x] #1 CITATION.cff added at repo root with correct metadata (sole author, ORCID, type: software, MIT, repo URL)
- [x] #2 One tagged GitHub release published and the Zenodo integration has minted a DOI
- [x] #3 Concept (all-versions) DOI recorded and handed to promotion repo TASK-37 AC#1
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Done via Zenodo GitHub-release pathway.
- CITATION.cff already at repo root (committed 33b7e13): sole author Ben Swift + ORCID 0000-0003-2138-5969, type: software, MIT, repo URL.
- Published release v2026.06 (target main @5bd80ae). Zenodo minted: version DOI 10.5281/zenodo.20842438, CONCEPT DOI 10.5281/zenodo.20842437.
- Concept DOI wired into benswift-cv.typ n-aps-tracker plate (promotion repo commit 49ba64f, TASK-37 AC#1) and CV recompiles clean.

CAVEAT: Zenodo ignored CITATION.cff and used bare GitHub metadata on the v2026.06 record -- no ORCID, generic title 'ANUcybernetics/aps-ai-transparency-tracker: v2026.06', affiliation '@ANUcybernetics'. DOI is unaffected. Fix the current record's metadata in the Zenodo web UI (DOI persists); add a .zenodo.json to the repo so future releases archive with correct metadata.
<!-- SECTION:NOTES:END -->
