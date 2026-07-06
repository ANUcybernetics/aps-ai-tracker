---
name: scrape
description:
  Runs the APS AI transparency tracker scraper, reviews the diff for quality,
  commits good changes and discards spurious ones, then searches for new
  transparency statements from agencies without URLs. Use when asked to
  "scrape", "run the scraper", "update statements", or "fetch transparency
  statements".
disable-model-invocation: true
model: sonnet
allowed-tools: Read, Grep, Glob, Bash, Edit, Agent, WebSearch, WebFetch
---

Run the APS AI transparency statement scraper, validate the results, commit
substantive changes, discard spurious ones, then search for newly published
statements from agencies that don't have URLs yet.

Never ask for confirmation or wait for user input at any step --- this skill
runs non-interactively from a cron job. Proceed immediately at every decision
point.

## Step 1: run the scraper

Run the full two-stage pipeline:

```
mise exec -- uv run --module aps_ai_transparency_tracker
```

Capture both stdout/stderr. The scraper logs to stderr. Note:

- exit code 0 means all agencies fetched and processed successfully
- exit code 1 means some agencies failed (check logs for details)
- a non-zero exit code does NOT mean no useful work was done --- many agencies
  may have succeeded
- HTML-sourced statements are extracted, cleaned, mdformatted and saved
  directly. PDF-sourced statements are saved as raw extracted text plus a
  `raw_hash` field in the frontmatter; the actual cleanup happens in Step 3
  below. If a PDF's raw text is unchanged from the previous scrape, the file
  isn't rewritten at all (so cleaned bodies aren't clobbered).

After the scraper finishes, report a brief summary: how many succeeded, how many
failed, and list any WARNING lines (especially CONTENT SHRINKAGE DETECTED and
LOW AI KEYWORD DENSITY).

## Step 2: clean PDF-sourced statements

PDF-sourced statement files are saved by the scraper as raw extracted text plus
a `raw_hash` field in the frontmatter. They need to be cleaned in this step
before the diff review.

List the files that need cleanup (files where `raw_hash` is set but
`cleaned_hash` is missing or doesn't match):

```
mise exec -- uv run python -c "
import yaml
from pathlib import Path
for p in sorted(Path('statements').glob('*.md')):
    parts = p.read_text(encoding='utf-8').split('---\n', 2)
    if len(parts) < 3:
        continue
    fm = yaml.safe_load(parts[1]) or {}
    raw = fm.get('raw_hash')
    if raw and raw != fm.get('cleaned_hash'):
        print(p)
"
```

For each file in the list, read it and rewrite the body in place. Apply these
transformations and **only** these transformations:

- Remove repeated `OFFICIAL`, `OFFICIAL: Sensitive`, `Classification: ...`
  markers (they're page watermarks, not content)
- Remove standalone page numbers and `Page N of M` headers/footers
- Remove dotted leader lines from tables of contents (e.g.
  `Introduction ........ 2`)
- Reflow paragraphs that were broken across PDF lines into normal prose ---
  collapse runs of single newlines into single spaces, but preserve real
  paragraph breaks (blank lines)
- Convert obvious headings to markdown headings (`#`, `##`, `###`) based on
  context (short, all-caps or title-case lines that introduce a section)
- Convert obvious bullet lists (lines starting with `•`, `-`, `*`, or numbered)
  to markdown lists with `-`

Do NOT:

- Add, remove, or rephrase any factual content
- Add commentary, headers, or footers of your own
- Translate or summarise
- Re-order sections

After cleaning, set `cleaned_hash` in the frontmatter equal to the existing
`raw_hash` and write the file back. The frontmatter format is:

```yaml
---
abbr: ABBR
agency: ...
source_url: ...
title: ...
raw_hash: <existing hash, leave unchanged>
cleaned_hash: <copy of raw_hash>
---
```

If a file's body looks like it was already mostly-clean text (e.g. the PDF was
already well-structured), you may end up writing back something close to the
original; that's fine. The point is to set `cleaned_hash` so the next scrape
treats it as cleaned.

## Step 3: review the diff

Use `git diff --stat` to see which files changed, then `git diff` to inspect the
actual changes.

Classify each changed file as **good** or **spurious**:

### Good changes

- actual content updates (new paragraphs, reworded sections, new information)
- new statement files appearing for the first time
- title changes that reflect real page updates
- URL changes in frontmatter (source_url or final_url) reflecting real redirects

### Spurious changes

- link URL parameter changes (tracking params, session IDs, cache busters)
- changes where only the YAML frontmatter order changed but values are identical
- trivially small changes (a single character or punctuation mark)
- content shrinkage --- if the scraper warned about CONTENT SHRINKAGE DETECTED,
  the new content is likely a scraping failure; discard that file's changes

Most other "noise" categories (whitespace-only diffs, date stamps, Cloudflare
email hashes, classification markers, "print this page" / social widgets, "you
may also be interested in" sidebars) are caught upstream by the deterministic
cleanup pipeline or by mdformat. If they reappear in a diff, that's a regression
in the cleanup pipeline rather than expected noise --- note it in the commit
description so it can be patched later, but don't manually discard the file.

If a file has a mix of good and spurious changes, keep it (the good outweighs
the noise). Only discard files where the changes are entirely spurious.

If in doubt about whether a change is good or spurious, keep it and mention it
in the commit description.

## Step 4: discard spurious changes

For each file classified as spurious, restore it:

```
git checkout HEAD -- <path>
```

After restoring all spurious files, run `git diff --stat` again to confirm only
good changes remain.

If ALL changes are spurious, restore everything and report that there were no
substantive updates:

```
git checkout HEAD -- .
```

## Step 5: commit and push

If there are good changes remaining:

1. Count the number of changed statement files with
   `git diff --stat | grep statements/`
2. Write a concise commit message in imperative mood. Use this pattern:
   - For statement updates:
     `update N transparency statements from latest scrape`
   - For mixed changes: `update N transparency statements, add M new`
   - Include a blank line then a brief list of notable changes if any agencies
     had warnings or interesting updates
3. Stage, commit, and push:

```
git add statements/
git commit -m "<message>"
git push
```

If there are no good changes, skip the commit and report that the scrape
produced no new content.

## Step 6: discover new and corrected statement URLs

After the scrape (whether or not there were updates), look for statements we're
missing or pointing at the wrong URL. The corpus is only as complete as our
discovery, so use **every source below**, not just one. Run both sources, then
reconcile. Proceed non-interactively --- act on the findings without asking.

### Source A --- the DTA register (authoritative cross-check)

The Digital Transformation Agency publishes the central register of every
Commonwealth AI transparency statement:

https://www.digital.gov.au/policy/ai/list-of-transparency-statements

Fetch it with `curl` and a browser User-Agent --- **not** WebFetch. WebFetch
often returns a partial or blocked render, and a truncated fetch is a fetch
failure, NOT proof a statement is missing (this is what made the register look
"partial" on 2026-06-26 --- the curl form has every entry, including the ones
WebFetch dropped). The curl form returns the full ~220 KB with every statement
link server-rendered:

```sh
curl -s -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36" \
  "https://www.digital.gov.au/policy/ai/list-of-transparency-statements" \
  | grep -oiE 'href="https?://[^"]*(ai-transparency|transparency-statement|ai-statement)[^"]*"' | sort -u
```

The grep is a starting filter, not exhaustive on URL shape --- a statement
linked via an unusual path or a PDF may not match it, so also eyeball the
register HTML for agency names that didn't surface a link. Then cross-check
against `agencies.toml` **both ways**:

- **tracked agency, `url = ""`, register has a link** --- candidate to add.
  Before adding, fetch the link and confirm it's real statement content: the
  register is authoritative for _whether_ an agency has published, not always
  for the _best URL_. Known traps --- stub pages that only link to a PDF we
  already track (ACQSC), and register URLs that 404 while ours works (Screen
  Australia); keep the working URL in those cases.
- **tracked agency, URL differs from the register's** --- only switch if the
  register URL is a better, working statement page.
- **register lists an agency not in `agencies.toml`** --- the register grows as
  more bodies publish, including voluntary statements from corporate
  Commonwealth entities and other bodies outside the APSC list. Policy: track
  any such body once it has a real statement. Fetch the link to confirm it's a
  genuine transparency statement (not a stub or 404), then add it to
  `agencies.toml` --- a unique abbr and a best-guess `size` --- so the next
  scrape picks up its first revision. Corporate/voluntary entities are in scope;
  add them, don't just report them. Note each addition in the run report.

### Source B --- targeted per-agency web search

For every agency still `url = ""` after the register pass, search the open web
--- it catches statements the register omits or links indirectly. Launch
subagents in parallel (batches of 5--6) with the Agent tool, each with
`model: "sonnet"` (Sonnet 5) --- targeted web search has a strict output shape,
so it doesn't need a stronger model. Each subagent should:

- WebSearch with several query shapes:
  - `"[agency name]" AI transparency statement site:[domain].gov.au`
  - `"[agency abbreviation]" AI transparency statement`
  - `site:[domain].gov.au artificial intelligence transparency`
- also try the common pattern directly:
  `https://[domain].gov.au/.../ai-transparency-statement`
- WebFetch any plausible hit to confirm it's an actual transparency statement
  (not a general AI-policy page), then return the verified URL or "not found".

### Reconcile and act

Combine the results from both sources, de-duplicated. For each verified
statement, set the `url` field in `agencies.toml`.

Some agencies legitimately stay `url = ""`: the policy excludes the defence
portfolio, the national intelligence community, and (mandatorily) corporate
Commonwealth entities, so DEFENCE, ASA, ACIC, ONI, NDIA, AHRC, AIATSIS and the
like keep coming back not-found --- that's expected, not a discovery failure.

If any URLs were added, re-run the scraper (the full pipeline picks up the new
URLs), review the diff, discard spurious changes, then commit and push:

```
git add agencies.toml statements/
git commit -m "add N new transparency statement URLs ([ABBR1], [ABBR2])"
git push
```

Report which agencies were checked, which source found what, and the outcome for
each: added / already-tracked / not-found / untracked-in-toml.

## Error handling

- If the scraper fails entirely (no output at all), report the error and stop
- If git commands fail, report the error and stop
- If there are content shrinkage warnings, mention the affected agencies in the
  summary so they can be investigated
- If there are low AI keyword density warnings, mention those too
- Never force-push or use destructive git operations
