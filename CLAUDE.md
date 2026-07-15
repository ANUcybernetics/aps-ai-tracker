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
  group: numpy + openai)
- Run tests: `mise exec -- uv run python -m pytest` (the `uv run pytest`
  console-script form does not resolve; invoke pytest as a module). Exporter
  tests live in `test_export.py`; run with `--group export` so numpy is present.
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
    with revert/noise collapse, lexical passage propagation, originality scores,
    OpenAI similarity with a committed content-hash cache)

## Static site (`site/`)

An Astro static site presents the data: a timeline of every change, agency and
per-statement pages (with a passage-reuse heat-map and revision time-travel), a
D3 similarity map, and a propagation explorer. Toolchain mirrors the benswift-me
repo: pnpm + Astro 7 + Svelte 5 islands, oxlint/oxfmt/stylelint, node 24. The
site is light-only (no dark mode); design tokens live in
`src/styles/tokens.css`.

- Dev: `cd site && mise exec -- pnpm dev`
- Build/lint/format/typecheck/test:
  `mise exec -- pnpm run {build,lint,format,typecheck,test}`
- Site unit tests use Vitest (`pnpm run test`); pure-TS helpers under `src/lib/`
  (e.g. `markdown.ts`) carry `*.test.ts` files. The exporter still uses pytest.
- The exporter writes gitignored JSON into `site/src/generated/`; only
  `.cache/embeddings.json` is committed. Run `export` before building the site
  locally. The client-fetched similarity graph is served by a build-time
  endpoint (`src/pages/data/similarity.graph.json.ts`) from the validated data.
- **Deploy**: live at <https://apsaitracker.app/> (apex custom domain; the
  `anucybernetics.github.io/aps-ai-tracker/` Pages URL 301-redirects to it, and
  the old `aps-ai-transparency-tracker` repo is a redirect stub for pre-rename
  links). The domain is pinned by `site/public/CNAME` **and** the Pages config
  `cname` (both needed: workflow deploys don't adopt the artifact CNAME on their
  own). `.github/workflows/deploy.yml` rebuilds + deploys to GitHub Pages on
  push to `main` (doc/ops/test-only pushes are skipped via `paths-ignore`). CI
  runs `export` **without** an OpenAI key (it reuses the committed embeddings
  cache), so no GitHub secret is needed. Pages is already configured (Settings →
  Pages → Source: GitHub Actions); only re-set that if it's ever reset. It
  serves from the domain root, so all internal links still go through
  `withBase()` in `site/src/lib/paths.ts`.
- **Embeddings happen on weddle**, not in CI: `cron-scrape.sh` runs `export`
  after the scrape (with `OPENAI_API_KEY` from weddle's global
  `~/.config/mise/config.local.toml`), commits the refreshed
  `.cache/embeddings.json`, and pushes. Statements are only re-embedded when
  their text changes, so most runs make zero API calls.

## atproto

The corpus is mirrored to the AT Protocol network under the project's own
account, `apsaitracker.bsky.social` (`did:plc:yhnshyrc2iev6z65u3uraon4`, PDS
bsky.social): a `site.standard.publication` for the site, one
`site.standard.document` per statement (full plaintext), and custom
`me.benswift.transparencyStatement` / `...StatementRevision` records --- one
mutable metadata record per agency plus an immutable record per observed
revision, chained via `prev`. Lexicon schemas live in `lexicons/` and are
published from Ben's personal DID (authority is `_lexicon.benswift.me`); the
data records live in the tracker account.

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
user unit on weddle. It scrapes (`claude -p "/scrape"`), refreshes the
embeddings cache (`export`), syncs the corpus to atproto (see above), and
`git push`es so the Pages site redeploys. weddle pushes to `origin` (credentials
confirmed working) and reads `OPENAI_API_KEY` from its global
`~/.config/mise/config.local.toml`. Canonical unit files live in `ops/systemd/`.
Install with:

```sh
cp ops/systemd/aps-scrape.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now aps-scrape.timer
```

Inspect runs with `journalctl --user -u aps-scrape.service -n 50`.

## Managing agency URLs

- `agencies.toml` lists the Australian Government bodies we track: the APSC-list
  agencies plus any corporate/voluntary entities discovered with a real
  statement (see the scrape skill's discovery step). The list grows over time,
  so don't assume a fixed count
- Each agency has a `url` field for their AI transparency statement
- Empty URLs (`url = ""`) are converted to `None` by the scraper
- **Tests fail for agencies with `None` URLs** - this is intentional
- Scraper skips agencies with `None` URLs when run
- When adding/fixing URLs:
  - Search for the agency's AI transparency statement via web search
  - Most follow pattern: `https://agency.gov.au/.../ai-transparency-statement`
  - If no statement exists, set `url = ""` (test will fail as a reminder)
  - Some agencies are exempt (NDIA, DEFENCE) or haven't published yet

## Code patterns

- Uses `dataclass` for data classes (Agency)
- Type hints throughout
- Returns dicts with explicit `str | int | None` types
- Handles both HTML and PDF sources
- Follows structured logging with stdlib `logging`
