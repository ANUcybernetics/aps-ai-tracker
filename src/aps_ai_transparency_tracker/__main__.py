"""Command-line entry point for the scraper."""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from .scraper import fetch_all_statements, load_agencies, logger, save_statement


def main() -> int:
    """Main execution function."""
    output_dir = Path.cwd() / "statements"
    agencies = load_agencies()

    logger.info(
        f"Starting AI Transparency Statement scrape at {datetime.now(UTC).isoformat()}"
    )
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Processing {len(agencies)} agencies")

    agencies_with_urls = [a for a in agencies if a.url is not None]
    skipped_count = len(agencies) - len(agencies_with_urls)

    for agency in agencies:
        if agency.url is None:
            logger.info(f"Skipping {agency.name} (no URL configured)")

    results = asyncio.run(fetch_all_statements(agencies_with_urls))

    success_count = 0
    error_count = 0

    for agency, data in results:
        if save_statement(agency, data, output_dir):
            success_count += 1
        else:
            error_count += 1

    logger.info(
        f"Completed: {success_count} successful, {error_count} errors, {skipped_count} skipped"
    )

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
