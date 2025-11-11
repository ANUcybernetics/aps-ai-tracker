"""Command-line entry point for the scraper."""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from .scraper import (
    fetch_all_raw,
    load_agencies,
    logger,
    process_raw,
    save_raw,
    save_statement,
)


def main() -> int:
    """Main execution function using two-stage pipeline: fetch raw -> process."""
    raw_dir = Path.cwd() / "raw"
    output_dir = Path.cwd() / "statements"
    agencies = load_agencies()

    logger.info(
        f"Starting AI Transparency Statement scrape at {datetime.now(UTC).isoformat()}"
    )
    logger.info(f"Raw directory: {raw_dir}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Processing {len(agencies)} agencies")

    # Filter agencies: exclude manual ones and those without URLs
    auto_agencies = [a for a in agencies if a.url is not None and not a.manual]
    manual_count = sum(1 for a in agencies if a.manual)
    skipped_count = sum(1 for a in agencies if a.url is None)

    if manual_count > 0:
        logger.info(f"Skipping {manual_count} manual agencies (use process_manual)")
    if skipped_count > 0:
        logger.info(f"Skipping {skipped_count} agencies without URLs")

    # Stage 1: Fetch raw content
    logger.info(f"Stage 1: Fetching raw content for {len(auto_agencies)} agencies...")
    raw_results = asyncio.run(fetch_all_raw(auto_agencies))

    fetch_success = 0
    for agency, data in raw_results:
        if save_raw(agency, data, raw_dir):
            fetch_success += 1

    logger.info(
        f"Stage 1 complete: {fetch_success}/{len(auto_agencies)} fetched successfully"
    )

    # Stage 2: Process raw content into statements
    logger.info("Stage 2: Processing raw content into statements...")
    process_success = 0
    process_error = 0

    for agency in auto_agencies:
        result = process_raw(agency, raw_dir)
        if save_statement(agency, result, output_dir):
            process_success += 1
        else:
            process_error += 1

    logger.info(
        f"Stage 2 complete: {process_success} successful, {process_error} errors"
    )
    logger.info(
        f"Overall: {process_success} statements updated, "
        f"{manual_count} manual, {skipped_count} skipped"
    )

    return 0 if process_error == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
