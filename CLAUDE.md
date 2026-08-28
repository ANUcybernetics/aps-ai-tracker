# Agent guidelines

This is a Python web scraping project using uv for dependency management.

## Key context

- Uses `uv` for package management with proper package structure
- Project has `mise.toml`---prefix commands with `mise exec --`
- Scrapes Australian Government AI transparency statements from agency websites
- Converts HTML/PDF to markdown with YAML frontmatter
- Tracks changes via git commits (designed for cron jobs)
- Dependencies defined in `pyproject.toml`: httpx, beautifulsoup4, html2text,
  lxml, mdformat, pypdf, pyyaml

## Working on this project

- Run scraper: `mise exec -- uv run --module aps_ai_tracker` (or the `scrape`
  entry point: `mise exec -- uv run scrape`)
- Reprocess cached `raw/` files into statements without refetching:
  `mise exec -- uv run process`
- Show collection status (statements vs agencies): `mise exec -- uv run status`
- Export site data (JSON for the Astro site):
  `mise exec -- uv run --group export export` (needs the `export` dependency
  group: pydantic + anthropic). Revision pairs and statement bodies not already
  in `.cache/changes.json` / `.cache/profiles.json` are sent to Claude (Sonnet
  by default; `APS_LLM_MODEL` overrides). The default backend shells out to
  `claude -p --json-schema` under the logged-in Claude Code subscription, with
  `ANTHROPIC_*` scrubbed from the child environment because Claude Code prefers
  an API key over the login; `APS_LLM_BACKEND=api` uses the SDK with an
  `ANTHROPIC_API_KEY` you pass explicitly for that run. **Never put an
  `ANTHROPIC_API_KEY` in this project's mise env**: every `claude` started in
  the repo, including the nightly `/scrape`, would silently bill it. With no
  backend the export degrades to the caches (unclassified pairs fall back to the
  commit-message noise heuristic; unprofiled bodies get `profile: null`)
- Run tests: `mise exec -- uv run python -m pytest` (the `uv run pytest`
  console-script form does not resolve; invoke pytest as a module). Scraper
  tests live in `test_scraper.py`, exporter tests in `test_export.py`; run the
  latter, plus `test_changes.py` and `test_profiles.py`, with `--group export`
  so pydantic is present.
- Typecheck: `mise exec -- uv run --group export --with ty ty check` (the export
  group so the pydantic/anthropic imports resolve; CI pins the ty version in
  `deploy.yml` — bump it there deliberately after a clean local run)
- Add agencies by editing `agencies.toml`
- Output goes to `statements/` directory
- Package structure:
  - `src/aps_ai_tracker/` contains the package
  - `scraper.py` has core functionality
  - `__main__.py` provides CLI entry point (the `scrape` command)
  - `process.py` reprocesses cached `raw/` files into statements without
    fetching
  - `status.py` reports collection status
  - `export.py` turns the corpus + git history into JSON for the site (timeline
    with revert collapse, lexical passage propagation, originality scores,
    concept adoption, statement currency)
  - `changes.py` classifies every consecutive revision pair from its diff:
    deterministic rules for formatting/link/chrome/date-stamp/reorder churn,
    Claude for the rest (kind + one-sentence summary + noteworthy points);
    cached by body-hash pair in `.cache/changes.json`
  - `profiles.py` reads each readable revision into a closed-vocabulary
    `Profile` (pydantic) aligned to the DTA Standard's minimum content and the
    policy v2.0 obligations, diffs consecutive profiles into labelled deltas,
    and derives the Standard report card and concept flags; cached by body hash
    in `.cache/profiles.json`
  - `adoption.py` builds the monthly concept-adoption series and per-statement
    currency (updated since policy v2.0, annual review overdue)
  - `llm.py` is the shared structured-extraction layer (backend selection,
    caches, concurrency). Bump a module's `SCHEMA_VERSION` after changing its
    prompt or schema; stale cache entries are ignored and pruned

## Static site (`site/`)

An Astro static site presents the data: a timeline of every change of substance
(each with its model-written summary), per-statement pages ("the story so far",
a profile report card against the Standard and policy v2.0, the text with a
passage-reuse heat-map, and every revision with time-travel), a "policy in
practice" page (adoption charts, commitments dropped, who is in charge,
staleness), and a propagation explorer. Toolchain mirrors the benswift-me repo:
pnpm + Astro 7 + Svelte 5 islands, oxlint/oxfmt/stylelint, node 24. The site is
light-only (no dark mode); design tokens live in `src/styles/tokens.css`.

- Dev: `cd site && mise exec -- pnpm dev`
- Build/lint/format/typecheck/test:
  `mise exec -- pnpm run {build,lint,format,typecheck,test}`
- Site unit tests use Vitest (`pnpm run test`); pure-TS helpers under `src/lib/`
  (e.g. `markdown.ts`) carry `*.test.ts` files. The exporter still uses pytest.
- The exporter writes gitignored JSON into `site/src/generated/`; only the
  `.cache/*.json` extraction caches are committed. Run `export` before building
  the site locally. Vocabulary labels for the profile fields live in
  `src/lib/profile-labels.ts`; keep them in step with `profiles.py`.
- **Deploy**: live at <https://apsaitracker.app/> (apex custom domain; the
  `anucybernetics.github.io/aps-ai-tracker/` Pages URL 301-redirects to it, and
  the old `aps-ai-transparency-tracker` repo is a redirect stub for pre-rename
  links). The domain is pinned by `site/public/CNAME` **and** the Pages config
  `cname` (both needed: workflow deploys don't adopt the artifact CNAME on their
  own). `.github/workflows/deploy.yml` rebuilds + deploys to GitHub Pages on
  push to `main` (doc/ops-only pushes are skipped via `paths-ignore`). CI is
  also the only place the Python tests and `ty` typecheck run automatically,
  ahead of the export step. CI runs `export` **without** any model access (it
  reuses the committed extraction caches), so no GitHub secret is needed. Pages
  is already configured (Settings → Pages → Source: GitHub Actions); only re-set
  that if it's ever reset. It serves from the domain root, so all internal links
  still go through `withBase()` in `site/src/lib/paths.ts`.
- **Model calls happen on weddle**, not in CI: `cron-scrape.sh` runs `export`
  after the scrape, which classifies the day's new revision pairs and profiles
  the changed bodies through `claude -p` (Sonnet, subscription), commits the
  refreshed `.cache/changes.json` and `.cache/profiles.json`, and pushes.
  Unchanged statements are cache hits, so most runs make a handful of calls or
  none. The history was backfilled with Opus 5; the cache records the model per
  entry.

## atproto

The corpus is mirrored to the AT Protocol network under the project's own
account, handle `apsaitracker.app` (a domain handle verified via the `_atproto`
TXT record; `did:plc:yhnshyrc2iev6z65u3uraon4`, PDS bsky.social): a
`site.standard.publication` for the site, one `site.standard.document` per
statement (full plaintext), and custom `me.benswift.transparencyStatement` /
`...StatementRevision` records --- one mutable metadata record per agency plus
an immutable record per observed revision, chained via `prev`. Lexicon schemas
live in `lexicons/` and are published from Ben's personal DID (authority is
`_lexicon.benswift.me`); the data records live in the tracker account.

- All rkeys are deterministic (agency abbr; `{abbr}-{compact UTC observedAt}`
  for revisions) so AT-URIs are computable, never stored. Shared constants and
  record builders: `site/src/lib/atproto.ts` (pure, env-free, vitest-covered).
- Sync: `cd site && mise exec -- pnpm run atproto:publish -- --write` (dry run
  without `--write`). Runs after `export` (reads `site/src/generated/`).
  Idempotent via record hashes in the committed `atproto-state.json`; deleting
  that file forces a safe full re-put. Auth: `APSAITRACKER_BSKY_TOKEN` in
  weddle's mise `config.local.toml`; the script refuses to write to any DID but
  the tracker's. The cron scrape runs this automatically and commits the state
  file.
- Dropping a statement from the corpus leaves its records live on the network.
  The script warns about the orphans and deletes them with `--prune` (records
  for any abbr in the state file but not the corpus, plus its revisions). The
  cron does **not** pass `--prune` --- pruning is destructive and a scrape
  glitch that loses a statement shouldn't erase its published history, so run it
  by hand after a deliberate removal.
- Schema changes: edit `lexicons/`, then
  `mise exec -- pnpm run atproto:lexicon -- --write` (uses the personal
  `ATP_IDENTIFIER`/`ATP_APP_PASSWORD`).
- Statement pages emit `site.standard.document`/`publication` `<link>` tags and
  the site serves `/.well-known/site.standard.publication` (kept by
  `include-hidden-files: true` in the Pages workflow).
- With `--crosspost` (the cron passes it), new substantive revisions are
  announced as skeets: one per agency per run (newest wins), capped at 25, noise
  never announced. Announced skeets are recorded in the committed
  `atproto-syndication.json` ledger — deliberately separate from the state file,
  so a state reset/backfill can never re-announce the back catalogue (`--seed`
  marks the whole corpus as already announced). Each skeet carries an external
  card with `associatedRefs` to the backing records, and the agency's document
  record is re-put with `bskyPostRef` pointing at its latest announcement.
- Bot profile (name/bio/avatar): `mise exec -- pnpm run atproto:profile`
  (idempotent; edit constants in `site/scripts/atproto-profile.ts`).

## Scheduled scrape

`cron-scrape.sh` runs daily at 03:00 local from `aps-scrape.timer`, a systemd
user unit on weddle. It scrapes (`/scrape` on Sonnet via
`~/.dotfiles/bin/agent-run --profile claude-sub`, which guarantees the
subscription route), refreshes the extraction caches (`export`), syncs the
corpus to atproto (see above), and `git push`es so the Pages site redeploys.
weddle pushes to `origin` (credentials confirmed working) and reads
`OPENAI_API_KEY` from its global `~/.config/mise/config.local.toml`. Canonical
unit files live in `ops/systemd/`. Install with:

```sh
cp ops/systemd/aps-scrape.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now aps-scrape.timer
```

The real run detail lives in `logs/scrape-YYYY-MM-DD.log` (gitignored, pruned
after 60 days) — the script redirects nearly all of its output there, so
`journalctl --user -u aps-scrape.service` only shows unit start/stop/exit.

## Managing agency URLs

- `agencies.toml` lists the Australian Government bodies we track: every
  non-corporate Commonwealth entity (NCE), plus any corporate/voluntary entity
  discovered with a real statement (see the scrape skill's discovery step). The
  list grows over time, so don't assume a fixed count
- Each agency has a `url` field for their AI transparency statement
- Each agency also has a `scope` field recording what the policy asks of it:
  - `mandatory` --- an NCE, bound by the policy
  - `voluntary` --- a corporate Commonwealth entity, Commonwealth company, or
    body outside the PGPA list; encouraged but not required to publish
  - `exempt` --- carved out entirely: the defence portfolio (incl. Veterans'
    Affairs) and the national intelligence community per s4 of the ONI Act (ONI,
    ASD, ASIO, ASIS, AGO, DIO, ACIC). Note AUSTRAC, AFP and Home Affairs are
    carved out only for their _intelligence_ functions, so as entities they are
    `mandatory` and have all published
- `scope` drives the site's coverage split, so it must be right: an NCE with no
  statement is a genuine gap (`not-yet`), not an exemption. Don't infer it from
  an empty URL
- Each agency also has a `portfolio` field (the portfolio per the Administrative
  Arrangements Order, short conventional name, "Parliament" for the
  parliamentary departments) used to group agencies on the site; keep the
  spelling consistent so identical portfolios collapse together
- Empty URLs (`url = ""`) are converted to `None` by the scraper
- **The `might_fail` fetch test fails for agencies with `None` URLs** - this is
  intentional, but that test is deselected by default (`-m might_fail` to run)
- Scraper skips agencies with `None` URLs when run
- When adding/fixing URLs:
  - Search for the agency's AI transparency statement via web search
  - Most follow pattern: `https://agency.gov.au/.../ai-transparency-statement`
  - If no statement exists, set `url = ""` (test will fail as a reminder)
- The authoritative roster of who exists and who is an NCE is Finance's [list of
  Commonwealth entities and companies][pgpa] (an xlsx, reissued each 1 July).
  Cross-check `agencies.toml` against it when auditing coverage --- it is what
  catches a newly created entity the DTA register hasn't picked up yet

[pgpa]:
  https://www.finance.gov.au/government/managing-commonwealth-resources/structure-australian-government-public-sector/pgpa-act-flipchart-and-list

## Code patterns

- Uses `dataclass` for data classes (Agency)
- Type hints throughout
- Returns dicts with explicit `str | int | None` types
- Handles both HTML and PDF sources
- Follows structured logging with stdlib `logging`
