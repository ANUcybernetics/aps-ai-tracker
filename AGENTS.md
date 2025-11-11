# Agent guidelines

This is a Python web scraping project using uv for dependency management.

## Key context

- Uses `uv` for package management with proper package structure
- Project has `mise.toml`---prefix commands with `mise exec --`
- Scrapes Australian Government AI transparency statements from agency websites
- Converts HTML/PDF to markdown with YAML frontmatter
- Tracks changes via git commits (designed for cron jobs)
- Dependencies defined in `pyproject.toml`: httpx, beautifulsoup4, html2text,
  lxml, pypdf, pyyaml

## Working on this project

- Run scraper: `mise exec -- uv run --module aps_ai_transparency_tracker`
- Run tests: `mise exec -- uv run pytest`
- Add agencies by editing `agencies.toml`
- Output goes to `statements/` directory
- Package structure:
  - `src/aps_ai_transparency_tracker/` contains the package
  - `scraper.py` has core functionality
  - `__main__.py` provides CLI entry point

## Managing agency URLs

- `agencies.toml` contains 110 Australian Government agencies
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

- Uses `NamedTuple` for data classes (Agency)
- Type hints throughout
- Returns dicts with explicit `str | int | None` types
- Handles both HTML and PDF sources
- Follows structured logging with stdlib `logging`
