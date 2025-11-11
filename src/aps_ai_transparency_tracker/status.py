"""Display status of AI transparency statement collection."""

import sys
from pathlib import Path

from .scraper import load_agencies, logger


def main() -> int:
    """Print count of processed statements and agency totals."""
    statements_dir = Path.cwd() / "statements"

    if not statements_dir.exists():
        logger.error(f"Error: {statements_dir} directory not found")
        return 1

    agencies = load_agencies()
    statement_files = list(statements_dir.glob("*.md"))

    total_agencies = len(agencies)
    statements_count = len(statement_files)

    print(f"Statements collected: {statements_count}/{total_agencies}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
