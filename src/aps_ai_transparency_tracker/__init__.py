"""Australian Government AI Transparency Statement Scraper."""

from .scraper import (
    Agency,
    StatementResult,
    clean_html_to_markdown,
    extract_main_content,
    fetch_statement,
    load_agencies,
    save_statement,
)

__all__ = [
    "Agency",
    "StatementResult",
    "clean_html_to_markdown",
    "extract_main_content",
    "fetch_statement",
    "load_agencies",
    "save_statement",
]
