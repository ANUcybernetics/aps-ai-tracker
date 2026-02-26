"""Australian Government AI Transparency Statement Scraper."""

from .scraper import (
    AI_KEYWORD_MIN_COUNT,
    CONTENT_SHRINKAGE_THRESHOLD,
    Agency,
    RawFetchResult,
    StatementResult,
    clean_html_to_markdown,
    clean_markdown,
    extract_main_content,
    extract_markdown_from_statement,
    fetch_all_raw,
    load_agencies,
    process_raw,
    save_raw,
    save_statement,
)

__all__ = [
    "AI_KEYWORD_MIN_COUNT",
    "CONTENT_SHRINKAGE_THRESHOLD",
    "Agency",
    "RawFetchResult",
    "StatementResult",
    "clean_html_to_markdown",
    "clean_markdown",
    "extract_main_content",
    "extract_markdown_from_statement",
    "fetch_all_raw",
    "load_agencies",
    "process_raw",
    "save_raw",
    "save_statement",
]
