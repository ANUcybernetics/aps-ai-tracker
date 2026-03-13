---
name: scrape
description:
  Runs the APS AI transparency tracker scraper, reviews the diff for quality,
  commits good changes and discards spurious ones, then searches for new
  transparency statements from agencies without URLs. Use when asked to "scrape",
  "run the scraper", "update statements", or "fetch transparency statements".
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash, Edit, WebSearch, WebFetch
---

Run the APS AI transparency statement scraper, validate the results, commit
substantive changes, discard spurious ones, then search for newly published
statements from agencies that don't have URLs yet.

Never ask for confirmation or wait for user input at any step --- this skill runs
non-interactively from a cron job. Proceed immediately at every decision point.

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

After the scraper finishes, report a brief summary: how many succeeded, how many
failed, and list any WARNING lines (especially CONTENT SHRINKAGE DETECTED and
LOW AI KEYWORD DENSITY).

## Step 2: review the diff

Use `git diff --stat` to see which files changed, then `git diff` to inspect the
actual changes.

Classify each changed file as **good** or **spurious**:

### Good changes

- actual content updates (new paragraphs, reworded sections, new information)
- new statement files appearing for the first time
- title changes that reflect real page updates
- URL changes in frontmatter (source_url or final_url) reflecting real redirects

### Spurious changes

- whitespace-only or formatting-only changes (line wrapping, trailing spaces)
- date stamp changes that leaked through cleaning ("last updated", "page
  updated", release dates in content)
- link URL parameter changes (tracking params, session IDs, cache busters)
- Cloudflare email protection hash changes (`cdn-cgi/l/email-protection`)
- boilerplate that leaked through removal (nav text, breadcrumbs, "print this
  page", social widgets, feedback prompts)
- changes where only the YAML frontmatter order changed but values are identical
- trivially small changes (a single character or punctuation mark)
- content shrinkage --- if the scraper warned about CONTENT SHRINKAGE DETECTED,
  the new content is likely a scraping failure; discard that file's changes

If a file has a mix of good and spurious changes, keep it (the good outweighs
the noise). Only discard files where the changes are entirely spurious.

If in doubt about whether a change is good or spurious, keep it and mention it
in the commit description.

## Step 3: discard spurious changes

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

## Step 4: commit and push

If there are good changes remaining:

1. Count the number of changed statement files with
   `git diff --stat | grep statements/`
2. Write a concise commit message in imperative mood. Use this pattern:
   - For statement updates: `update N transparency statements from latest scrape`
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

## Step 5: search for new transparency statements

After the scrape is complete (whether or not there were updates), search for
newly published statements from agencies that currently have no URL.

1. Read `agencies.toml` and collect all agencies where `url = ""`.
2. Pick up to 5 agencies to search for. Prioritise larger agencies (by `size`)
   and rotate through them across runs --- pick the ones that appear earliest in
   the file that you haven't found yet, so over multiple weeks all agencies get
   checked.
3. For each selected agency, use WebSearch to look for their AI transparency
   statement:
   - `"[agency name]" AI transparency statement site:[domain].gov.au`
   - `"[agency abbreviation]" AI transparency statement`
   - `site:[domain].gov.au artificial intelligence transparency`
4. If a search returns a plausible result, use WebFetch to visit the page and
   verify it's actually an AI transparency statement (not a general policy page
   or unrelated content).
5. For each verified statement found, update the `url` field in `agencies.toml`.
6. If any URLs were added, run the scraper again (the full pipeline --- it will
   pick up the new URLs), then review the diff, discard spurious changes, and
   commit and push:

   ```
   git add agencies.toml statements/
   git commit -m "add N new transparency statement URLs ([ABBR1], [ABBR2])"
   git push
   ```

7. If no new statements were found, report which agencies were checked and that
   nothing was found.

## Error handling

- If the scraper fails entirely (no output at all), report the error and stop
- If git commands fail, report the error and stop
- If there are content shrinkage warnings, mention the affected agencies in the
  summary so they can be investigated
- If there are low AI keyword density warnings, mention those too
- Never force-push or use destructive git operations
