"""Command-line entry point for the scraper."""

import asyncio
import sys
from datetime import UTC, datetime

from .scraper import (
    REPO_ROOT,
    fetch_all_raw,
    fetch_raw_browser,
    load_agencies,
    logger,
    process_statements,
    save_raw,
)


def main() -> int:
    """Main execution function using two-stage pipeline: fetch raw -> process."""
    raw_dir = REPO_ROOT / "raw"
    output_dir = REPO_ROOT / "statements"
    agencies = load_agencies()

    logger.info(
        f"Starting AI Transparency Statement scrape at {datetime.now(UTC).isoformat()}"
    )
    logger.info(f"Raw directory: {raw_dir}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Processing {len(agencies)} agencies")

    # Filter agencies: exclude manual ones and those without URLs
    auto_agencies = [a for a in agencies if a.url is not None and not a.manual]
    # The browser path is serial and slow, so it runs on its own after the
    # concurrent httpx batch rather than inside it.
    http_agencies = [a for a in auto_agencies if not a.browser]
    browser_agencies = [a for a in auto_agencies if a.browser]
    manual_count = sum(1 for a in agencies if a.manual)
    skipped_count = sum(1 for a in agencies if a.url is None)

    if manual_count > 0:
        logger.info(
            f"Skipping {manual_count} manual agencies (maintained via the scrape skill)"
        )
    if skipped_count > 0:
        logger.info(f"Skipping {skipped_count} agencies without URLs")

    # Stage 1: Fetch raw content
    logger.info(f"Stage 1: Fetching raw content for {len(auto_agencies)} agencies...")
    raw_results = asyncio.run(fetch_all_raw(http_agencies))
    if browser_agencies:
        logger.info(
            f"Fetching {len(browser_agencies)} bot-challenged agencies "
            "through the browser..."
        )
        raw_results += [(a, fetch_raw_browser(a)) for a in browser_agencies]

    fetch_success = 0
    for agency, data in raw_results:
        if save_raw(agency, data, raw_dir):
            fetch_success += 1

    logger.info(
        f"Stage 1 complete: {fetch_success}/{len(auto_agencies)} fetched successfully"
    )

    # Stage 2: Process raw content into statements
    logger.info("Stage 2: Processing raw content into statements...")
    counts = process_statements(auto_agencies, raw_dir, output_dir)

    logger.info(
        f"Stage 2 complete: {counts.saved + counts.warned} successful, "
        f"{counts.failed} errors"
    )
    if counts.warned:
        logger.warning(
            f"{counts.warned} statement(s) shrank past the threshold; "
            "review the diffs before committing"
        )
    logger.info(
        f"Overall: {counts.saved + counts.warned} statements updated, "
        f"{manual_count} manual, {skipped_count} skipped"
    )

    fetch_failures = len(auto_agencies) - fetch_success
    # Shrinkage joins genuine failures in the exit code: the nightly run
    # auto-commits, so a suspicious diff must surface where the cron agent looks.
    ok = fetch_failures == 0 and counts.failed == 0 and counts.warned == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
