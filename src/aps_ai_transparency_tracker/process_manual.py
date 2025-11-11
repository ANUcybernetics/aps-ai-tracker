"""Process manually-saved raw HTML/PDF files into statements."""

import sys
from datetime import UTC, datetime
from pathlib import Path

from .scraper import load_agencies, logger, process_raw, save_statement


def main() -> int:
    """Process all raw files for agencies marked as manual=true."""
    raw_dir = Path.cwd() / "raw"
    output_dir = Path.cwd() / "statements"

    if not raw_dir.exists():
        logger.error(f"Error: {raw_dir} directory not found")
        return 1

    agencies = load_agencies()
    manual_agencies = [a for a in agencies if a.manual]

    if not manual_agencies:
        logger.info("No agencies marked as manual=true")
        return 0

    logger.info(f"Starting manual processing at {datetime.now(UTC).isoformat()}")
    logger.info(f"Raw directory: {raw_dir}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Processing {len(manual_agencies)} manual agencies")

    success_count = 0
    error_count = 0
    missing_count = 0

    for agency in manual_agencies:
        # Check if raw file exists (HTML or PDF)
        html_path = raw_dir / f"{agency.abbr}.html"
        pdf_path = raw_dir / f"{agency.abbr}.pdf"

        if not html_path.exists() and not pdf_path.exists():
            logger.warning(
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

    return 0 if error_count == 0 and missing_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
