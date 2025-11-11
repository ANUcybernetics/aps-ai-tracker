"""Process all cached raw HTML/PDF files into statements without fetching."""

import sys
from datetime import UTC, datetime
from pathlib import Path

from .scraper import load_agencies, logger, process_raw, save_statement


def main() -> int:
    """Process all existing raw files into statements without fetching."""
    raw_dir = Path.cwd() / "raw"
    output_dir = Path.cwd() / "statements"

    if not raw_dir.exists():
        logger.error(f"Error: {raw_dir} directory not found")
        return 1

    agencies = load_agencies()

    logger.info(f"Starting processing at {datetime.now(UTC).isoformat()}")
    logger.info(f"Raw directory: {raw_dir}")
    logger.info(f"Output directory: {output_dir}")

    success_count = 0
    error_count = 0
    missing_count = 0

    for agency in agencies:
        html_path = raw_dir / f"{agency.abbr}.html"
        pdf_path = raw_dir / f"{agency.abbr}.pdf"

        if not html_path.exists() and not pdf_path.exists():
            logger.debug(
                f"No raw file found for {agency.abbr} "
                f"(expected {html_path.name} or {pdf_path.name})"
            )
            missing_count += 1
            continue

        logger.info(f"Processing {agency.abbr}...")
        result = process_raw(agency, raw_dir)

        if save_statement(agency, result, output_dir):
            success_count += 1
        else:
            error_count += 1

    logger.info(
        f"Completed: {success_count} successful, "
        f"{error_count} errors, {missing_count} missing raw files"
    )

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
