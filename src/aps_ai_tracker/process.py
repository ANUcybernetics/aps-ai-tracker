"""Process all cached raw HTML/PDF files into statements without fetching."""

import sys
from datetime import UTC, datetime

from .scraper import (
    REPO_ROOT,
    Agency,
    load_agencies,
    logger,
    process_statements,
)


def main() -> int:
    """Process all existing raw files into statements without fetching."""
    raw_dir = REPO_ROOT / "raw"
    output_dir = REPO_ROOT / "statements"

    if not raw_dir.exists():
        logger.error(f"Error: {raw_dir} directory not found")
        return 1

    agencies = load_agencies()

    logger.info(f"Starting processing at {datetime.now(UTC).isoformat()}")
    logger.info(f"Raw directory: {raw_dir}")
    logger.info(f"Output directory: {output_dir}")

    present: list[Agency] = []
    missing_count = 0
    for agency in agencies:
        html_path = raw_dir / f"{agency.abbr}.html"
        pdf_path = raw_dir / f"{agency.abbr}.pdf"
        if html_path.exists() or pdf_path.exists():
            present.append(agency)
        else:
            logger.debug(
                f"No raw file found for {agency.abbr} "
                f"(expected {html_path.name} or {pdf_path.name})"
            )
            missing_count += 1

    counts = process_statements(present, raw_dir, output_dir)

    logger.info(
        f"Completed: {counts.saved + counts.warned} successful, "
        f"{counts.failed} errors, {missing_count} missing raw files"
    )
    if counts.warned:
        logger.warning(
            f"{counts.warned} statement(s) shrank past the threshold; "
            "review the diffs before committing"
        )

    return 0 if counts.failed == 0 and counts.warned == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
