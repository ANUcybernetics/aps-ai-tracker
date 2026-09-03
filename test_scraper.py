"""
Smoke tests for AI Transparency Statement scraper.

Tests verify basic functionality and invariants without asserting
on external content that may change.

Usage:
    uv run pytest test_scraper.py -v
"""

import asyncio
import hashlib
import json
import re
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml
from bs4 import BeautifulSoup

from aps_ai_tracker import (
    CONTENT_SHRINKAGE_THRESHOLD,
    Agency,
    ProcessCounts,
    RawFetchResult,
    StatementResult,
    atomic_write_text,
    clean_html_to_markdown,
    clean_markdown,
    decode_cf_email,
    extract_main_content,
    extract_markdown_from_statement,
    fetch_all_raw,
    fetch_raw_browser,
    load_agencies,
    overdue,
    process_raw,
    process_statements,
    save_raw,
    save_statement,
)


def fetch_statement(agency: Agency) -> StatementResult:
    """Helper for the might_fail integration tests: fetch + process one agency."""
    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        raw_results = asyncio.run(fetch_all_raw([agency]))
        if raw_results:
            _, raw_data = raw_results[0]
            save_raw(agency, raw_data, raw_dir)
            return process_raw(agency, raw_dir)
        return {
            "title": None,
            "markdown": None,
            "status_code": None,
            "final_url": agency.url,
            "error": "Fetch failed",
            "source_type": None,
        }


def process_fixture_statement() -> StatementResult:
    """Process a local HTML fixture through the raw pipeline (no network)."""
    agency = Agency(
        name="Fixture Agency", abbr="FIXTURE", url="https://example.com/statement"
    )
    html = """
    <html>
        <head><title>Fixture Statement</title></head>
        <body><main><h1>AI use</h1><p>We use AI carefully.</p></main></body>
    </html>
    """
    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        (raw_dir / "FIXTURE.html").write_text(html, encoding="utf-8")
        return process_raw(agency, raw_dir)


def test_agencies_list_structure():
    """Verify agencies list has required structure."""
    agencies = load_agencies()
    assert len(agencies) > 0
    for agency in agencies:
        assert isinstance(agency, Agency)
        assert agency.name
        assert agency.abbr
        assert agency.url is None or agency.url.startswith("http")


def test_manual_agencies_record_why():
    """Nothing refreshes a manual agency, so each must say why it is one.

    An unexplained `manual = true` is invisible: the entry simply stops being
    scraped and its statement freezes with nothing on the record to say so.
    """
    unexplained = [a.abbr for a in load_agencies() if a.manual and not a.manual_reason]
    assert not unexplained, f"manual agencies without a manual_reason: {unexplained}"


def test_browser_agencies_record_why():
    """The browser path is serial and slow, so each user of it must say which
    challenge earns it, and no agency may be both browser-fetched and manual."""
    agencies = load_agencies()
    unexplained = [a.abbr for a in agencies if a.browser and not a.browser_reason]
    assert not unexplained, f"browser agencies without a browser_reason: {unexplained}"
    both = [a.abbr for a in agencies if a.browser and a.manual]
    assert not both, f"agencies marked both browser and manual: {both}"


def test_last_verified_is_an_iso_date():
    """last_verified feeds the staleness check, which needs a parseable date."""
    for agency in load_agencies():
        if agency.last_verified:
            date.fromisoformat(agency.last_verified)


def test_agencies_unique_abbrs():
    """Ensure all agency abbreviations are unique."""
    agencies = load_agencies()
    abbrs = [a.abbr for a in agencies]
    assert len(abbrs) == len(set(abbrs))


def test_clean_html_to_markdown_basic():
    """Test HTML to markdown conversion produces valid output."""
    html = "<h1>Test Title</h1><p>Some content</p>"
    markdown = clean_html_to_markdown(html, "https://example.com")

    assert "Test Title" in markdown
    assert "Some content" in markdown
    assert len(markdown) > 0


def test_clean_html_to_markdown_removes_excess_newlines():
    """Test that excessive newlines are cleaned up."""
    html = "<p>Para 1</p>\n\n\n\n<p>Para 2</p>"
    markdown = clean_html_to_markdown(html, "https://example.com")

    # Should not have more than 2 consecutive newlines
    assert "\n\n\n" not in markdown


def test_extract_main_content_with_main_tag():
    """Test extraction when main tag exists."""
    html = """
    <html>
        <nav>Navigation</nav>
        <main>Main content here</main>
        <footer>Footer</footer>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    content = extract_main_content(soup)

    assert "Main content here" in content
    assert isinstance(content, str)


def test_extract_main_content_fallback():
    """Test extraction falls back to body when no main tag."""
    html = """
    <html>
        <body>
            <nav>Navigation</nav>
            <div>Body content</div>
            <footer>Footer</footer>
        </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    content = extract_main_content(soup)

    assert "Body content" in content
    # Nav and footer should be removed
    assert "Navigation" not in content
    assert "Footer" not in content


def test_extract_main_content_selector_keeps_every_match():
    """A selector matching sibling blocks yields all of them, in document order
    (NFSA splits standfirst, body and download link across .article-content)."""
    html = """
    <html>
        <body>
            <main>
                <div class="article-content">Standfirst.</div>
                <div class="article-content"><nav>Menu</nav>Body of the statement.</div>
                <div class="promo">Buy tickets</div>
                <div class="article-content">Download the statement.</div>
            </main>
        </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    content = extract_main_content(soup, ".article-content")

    assert content.index("Standfirst.") < content.index("Body of the statement.")
    assert content.index("Body of the statement.") < content.index(
        "Download the statement."
    )
    assert "Buy tickets" not in content
    assert "Menu" not in content


def test_extract_main_content_removes_boilerplate_from_main():
    """Test boilerplate removal works even when main tag is present."""
    html = """
    <html>
        <body>
            <main>
                <nav class="breadcrumb">Home > Page</nav>
                <header class="page-header">Page Header</header>
                <div>Main content here</div>
                <aside role="complementary">Sidebar content</aside>
                <footer class="site-footer">Footer content</footer>
            </main>
        </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    content = extract_main_content(soup)

    assert "Main content here" in content
    # Boilerplate should be removed even within main tag
    assert "Home > Page" not in content
    assert "Page Header" not in content
    assert "Sidebar content" not in content
    assert "Footer content" not in content


def test_statement_result_returns_required_fields():
    """The StatementResult contract: exactly the expected keys, no network."""
    result = process_fixture_statement()

    required_fields = {
        "title",
        "markdown",
        "status_code",
        "final_url",
        "error",
        "source_type",
        "last_updated",
    }
    assert set(result.keys()) == required_fields


def test_statement_result_success_shape():
    """A successful processing run carries the full result payload."""
    result = process_fixture_statement()

    assert result["error"] is None
    assert result["status_code"] == 200
    markdown_content = result["markdown"]
    assert isinstance(markdown_content, str) and len(markdown_content) > 0
    assert result["final_url"] is not None


def test_statement_result_type_consistency():
    """StatementResult fields carry consistent types."""
    result = process_fixture_statement()

    assert result["title"] is None or isinstance(result["title"], str)
    assert result["markdown"] is None or isinstance(result["markdown"], str)
    assert result["status_code"] is None or isinstance(result["status_code"], int)
    assert isinstance(result["final_url"], str)
    assert result["error"] is None or isinstance(result["error"], str)


def test_save_statement_creates_valid_file():
    """Test save_statement creates properly formatted file."""
    dept = Agency(name="Test Agency", abbr="TEST", url="https://example.com/test")

    data: StatementResult = {
        "title": "Test Statement",
        "markdown": "# Test Content\n\nSome text here.",
        "status_code": 200,
        "final_url": "https://example.com/test",
        "error": None,
        "source_type": "html",
    }

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        result = save_statement(dept, data, output_dir)

        assert result == "saved"
        filepath = output_dir / "TEST.md"
        assert filepath.exists()

        content = filepath.read_text()

        # Should start with YAML frontmatter
        assert content.startswith("---\n")

        # Should have closing frontmatter delimiter
        parts = content.split("---\n")
        assert len(parts) >= 3

        # YAML should be valid
        yaml_content = parts[1]
        metadata = yaml.safe_load(yaml_content)
        assert metadata["agency"] == "Test Agency"
        assert metadata["abbr"] == "TEST"
        assert metadata["source_url"] == "https://example.com/test"
        assert metadata["title"] == "Test Statement"

        # Should not have removed fields
        assert "status_code" not in metadata
        assert "error" not in metadata

        # final_url should not be present when it matches source_url
        assert "final_url" not in metadata

        # Markdown content should be present
        assert "# Test Content" in content


def test_save_statement_cleans_pdf_body_but_hashes_raw():
    """PDF bodies get the deterministic clean_markdown pass (OFFICIAL markers, nav
    chrome), while raw_hash stays keyed on the raw text so PDF-change detection is
    unaffected."""
    agency = Agency(
        name="Test Agency", abbr="TEST-PDF", url="https://example.com/s.pdf"
    )
    raw = (
        "Classification: OFFICIAL\n\n"
        "# AI Statement\n\n"
        "We use AI responsibly.\n\n"
        "Back to top\n"
    )
    data: StatementResult = {
        "title": "PDF Statement",
        "markdown": raw,
        "status_code": 200,
        "final_url": "https://example.com/s.pdf",
        "error": None,
        "source_type": "pdf",
    }

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        assert save_statement(agency, data, output_dir) == "saved"
        content = (output_dir / "TEST-PDF.md").read_text()
        metadata = yaml.safe_load(content.split("---\n")[1])

        # Chrome and classification markers are stripped from the written body.
        assert "OFFICIAL" not in content
        assert "Back to top" not in content
        assert "We use AI responsibly." in content
        # raw_hash keys on the RAW extracted text, not the cleaned body.
        assert metadata["raw_hash"] == hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_save_statement_handles_error_case():
    """Test save_statement skips file creation when there's an error."""
    dept = Agency(name="Test Agency", abbr="TEST-ERROR", url="https://example.com/test")

    data: StatementResult = {
        "title": None,
        "markdown": None,
        "status_code": 404,
        "final_url": "https://example.com/test",
        "error": "Not found",
        "source_type": None,
    }

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        result = save_statement(dept, data, output_dir)

        # Should report failure and not create the file
        assert result == "failed"
        filepath = output_dir / "TEST-ERROR.md"
        assert not filepath.exists()


def test_save_statement_handles_no_content():
    """Test save_statement skips file creation when there's no markdown."""
    dept = Agency(name="Test Agency", abbr="TEST-EMPTY", url="https://example.com/test")

    data: StatementResult = {
        "title": None,
        "markdown": None,
        "status_code": 200,
        "final_url": "https://example.com/test",
        "error": None,
        "source_type": None,
    }

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        result = save_statement(dept, data, output_dir)

        # Should report failure and not create the file
        assert result == "failed"
        filepath = output_dir / "TEST-EMPTY.md"
        assert not filepath.exists()


def test_save_statement_includes_final_url_on_redirect():
    """Test save_statement includes final_url when it differs from source_url."""
    dept = Agency(
        name="Test Agency", abbr="TEST-REDIRECT", url="https://example.com/old"
    )

    data: StatementResult = {
        "title": "Test Statement",
        "markdown": "# Test Content",
        "status_code": 200,
        "final_url": "https://example.com/new",
        "error": None,
        "source_type": "html",
    }

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        result = save_statement(dept, data, output_dir)

        assert result == "saved"
        filepath = output_dir / "TEST-REDIRECT.md"
        content = filepath.read_text()

        parts = content.split("---\n")
        yaml_content = parts[1]
        metadata = yaml.safe_load(yaml_content)

        # final_url should be present when it differs from source_url
        assert metadata["final_url"] == "https://example.com/new"
        assert metadata["source_url"] == "https://example.com/old"


def test_save_raw_html():
    """Test save_raw saves HTML content and metadata correctly."""
    agency = Agency(name="Test Agency", abbr="TEST-HTML", url="https://example.com")

    html_content = b"<html><body><h1>Test</h1></body></html>"
    data: RawFetchResult = {
        "content": html_content,
        "content_type": "text/html; charset=utf-8",
        "status_code": 200,
        "final_url": "https://example.com/final",
        "error": None,
    }

    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        result = save_raw(agency, data, raw_dir)

        assert result is True
        filepath = raw_dir / "TEST-HTML.html"
        assert filepath.exists()
        assert filepath.read_bytes() == html_content

        meta = json.loads((raw_dir / "TEST-HTML.meta.json").read_text())
        assert meta["final_url"] == "https://example.com/final"
        assert meta["content_type"] == "text/html; charset=utf-8"


def test_save_raw_pdf():
    """Test save_raw saves PDF content and metadata correctly."""
    agency = Agency(name="Test Agency", abbr="TEST-PDF", url="https://example.com")

    pdf_content = b"%PDF-1.4 fake pdf content"
    data: RawFetchResult = {
        "content": pdf_content,
        "content_type": "application/pdf",
        "status_code": 200,
        "final_url": "https://example.com",
        "error": None,
    }

    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        result = save_raw(agency, data, raw_dir)

        assert result is True
        filepath = raw_dir / "TEST-PDF.pdf"
        assert filepath.exists()
        assert filepath.read_bytes() == pdf_content

        meta = json.loads((raw_dir / "TEST-PDF.meta.json").read_text())
        assert meta["final_url"] == "https://example.com"
        assert meta["content_type"] == "application/pdf"


def test_save_raw_handles_error():
    """Test save_raw skips saving when there's an error."""
    agency = Agency(name="Test Agency", abbr="TEST-ERROR", url="https://example.com")

    data: RawFetchResult = {
        "content": None,
        "content_type": None,
        "status_code": 404,
        "final_url": "https://example.com",
        "error": "Not found",
    }

    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        result = save_raw(agency, data, raw_dir)

        assert result is False
        assert not (raw_dir / "TEST-ERROR.html").exists()
        assert not (raw_dir / "TEST-ERROR.pdf").exists()


def test_process_raw_html():
    """Test process_raw converts HTML to markdown."""
    agency = Agency(name="Test Agency", abbr="TEST-PROC", url="https://example.com")

    html_content = """
    <html>
        <head><title>Test Title</title></head>
        <body>
            <main>
                <h1>Test Heading</h1>
                <p>Test paragraph content.</p>
            </main>
        </body>
    </html>
    """

    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        (raw_dir / "TEST-PROC.html").write_text(html_content, encoding="utf-8")

        result = process_raw(agency, raw_dir)

        assert result["error"] is None
        assert result["status_code"] == 200
        assert result["title"] == "Test Title"
        assert result["final_url"] == agency.url
        assert result["markdown"] is not None
        markdown_content = result["markdown"]
        assert isinstance(markdown_content, str)
        assert "Test Heading" in markdown_content
        assert "Test paragraph content" in markdown_content


def test_process_raw_uses_metadata_final_url():
    """Test process_raw reads final_url from metadata file."""
    agency = Agency(name="Test Agency", abbr="TEST-META", url="https://example.com/old")

    html_content = "<html><body><main><p>Content</p></main></body></html>"

    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        (raw_dir / "TEST-META.html").write_text(html_content, encoding="utf-8")
        (raw_dir / "TEST-META.meta.json").write_text(
            json.dumps(
                {"final_url": "https://example.com/new", "content_type": "text/html"}
            ),
            encoding="utf-8",
        )

        result = process_raw(agency, raw_dir)

        assert result["error"] is None
        assert result["final_url"] == "https://example.com/new"


def test_process_raw_missing_file():
    """Test process_raw handles missing raw file."""
    agency = Agency(name="Test Agency", abbr="MISSING", url="https://example.com")

    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        result = process_raw(agency, raw_dir)

        assert result["error"] == "No raw file found for MISSING"
        assert result["markdown"] is None
        assert result["status_code"] is None


def test_process_raw_invalid_html():
    """Test process_raw handles invalid HTML gracefully."""
    agency = Agency(name="Test Agency", abbr="BAD-HTML", url="https://example.com")

    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        (raw_dir / "BAD-HTML.html").write_bytes(b"\x00\x01\x02invalid")

        result = process_raw(agency, raw_dir)

        # Should handle gracefully, though result may vary
        assert isinstance(result, dict)
        assert "error" in result


@pytest.mark.might_fail
@pytest.mark.parametrize("agency", load_agencies(), ids=lambda a: a.abbr)
def test_all_agencies_can_be_fetched(agency):
    """Integration test: verify all agencies in agencies.toml can be fetched and parsed.

    Skipped by default. Run with: pytest -m might_fail
    """
    # Skip agencies without URLs (where AI statement not found)
    # Tests should fail for agencies without URLs (not skip)
    # The scraper itself will skip them when run
    if agency.url is None:
        pytest.fail(
            f"{agency.name} ({agency.abbr}): No URL configured. "
            "Either find the AI transparency statement URL or confirm none exists."
        )

    result = fetch_statement(agency)

    # Verify result structure
    assert isinstance(result, dict), f"{agency.abbr}: result is not a dict"
    assert "error" in result, f"{agency.abbr}: missing 'error' field"

    # If there's an error, fail with descriptive message
    if result["error"] is not None:
        pytest.fail(
            f"{agency.name} ({agency.abbr}): {result['error']} "
            f"(status: {result['status_code']}, url: {agency.url})"
        )

    # Verify successful fetch has required content
    assert result["status_code"] == 200, f"{agency.abbr}: status code not 200"
    assert result["markdown"], f"{agency.abbr}: no markdown content"
    markdown_content = result["markdown"]
    assert isinstance(markdown_content, str) and len(markdown_content) > 0, (
        f"{agency.abbr}: empty markdown"
    )


# Tests for content shrinkage detection


def test_extract_markdown_from_statement_valid_file():
    """Test extracting markdown from a valid statement file."""
    with TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "TEST.md"
        content = """---
agency: Test Agency
abbr: TEST
source_url: https://example.com
title: Test Title
---

# Heading

Some markdown content here."""
        filepath.write_text(content, encoding="utf-8")

        result = extract_markdown_from_statement(filepath)

        assert result is not None
        assert "# Heading" in result
        assert "Some markdown content here." in result
        # Should not include frontmatter
        assert "agency:" not in result


def test_extract_markdown_from_statement_missing_file():
    """Test extracting markdown from non-existent file."""
    with TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "MISSING.md"

        result = extract_markdown_from_statement(filepath)

        assert result is None


def test_extract_markdown_from_statement_invalid_format():
    """Test extracting markdown from file without proper frontmatter."""
    with TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "INVALID.md"
        filepath.write_text(
            "Just some plain text without frontmatter", encoding="utf-8"
        )

        result = extract_markdown_from_statement(filepath)

        assert result is None


def test_save_statement_warns_on_content_shrinkage(caplog):
    """Test that save_statement logs a warning when content shrinks significantly."""
    agency = Agency(name="Test Agency", abbr="TEST-SHRINK", url="https://example.com")

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        # First, create an existing statement with substantial content
        existing_content = """---
agency: Test Agency
abbr: TEST-SHRINK
source_url: https://example.com
title: Original Title
---

# Original Content

This is a substantial amount of content that represents a properly
scraped page. It has multiple paragraphs and sections.

## Section 1

Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do
eiusmod tempor incididunt ut labore et dolore magna aliqua.

## Section 2

Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris
nisi ut aliquip ex ea commodo consequat."""

        (output_dir / "TEST-SHRINK.md").write_text(existing_content, encoding="utf-8")

        # Now save a much smaller statement (simulating a scraping failure)
        small_data: StatementResult = {
            "title": "New Title",
            "markdown": "# Short\n\nVery little content.",
            "status_code": 200,
            "final_url": "https://example.com",
            "error": None,
            "source_type": "html",
        }

        import logging

        with caplog.at_level(logging.WARNING):
            result = save_statement(agency, small_data, output_dir)

        # Still writes the file (so the diff is reviewable), but reports the
        # shrinkage so the pipeline exit code can flag it.
        assert result == "warned"
        assert (output_dir / "TEST-SHRINK.md").exists()

        # Should have logged a warning about content shrinkage
        assert any(
            "CONTENT SHRINKAGE DETECTED" in record.message for record in caplog.records
        )
        assert any("TEST-SHRINK" in record.message for record in caplog.records)


def test_save_statement_no_warning_on_similar_size():
    """Test that save_statement does not warn when content size is similar."""
    agency = Agency(name="Test Agency", abbr="TEST-SIMILAR", url="https://example.com")

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        # Create an existing statement
        existing_content = """---
agency: Test Agency
abbr: TEST-SIMILAR
source_url: https://example.com
title: Original Title
---

# Content

This is some content that will be replaced with similar-length content."""

        (output_dir / "TEST-SIMILAR.md").write_text(existing_content, encoding="utf-8")

        # Save a new statement with similar amount of content
        new_data: StatementResult = {
            "title": "New Title",
            "markdown": "# Updated Content\n\nThis is updated content that has roughly the same length as before.",
            "status_code": 200,
            "final_url": "https://example.com",
            "error": None,
            "source_type": "html",
        }

        from unittest.mock import patch

        # Capture log output
        with patch("aps_ai_tracker.scraper.logger") as mock_logger:
            result = save_statement(agency, new_data, output_dir)

        # Should save successfully
        assert result == "saved"

        # Should NOT have logged a warning (only info)
        warning_calls = [
            call
            for call in mock_logger.warning.call_args_list
            if "CONTENT SHRINKAGE" in str(call)
        ]
        assert len(warning_calls) == 0


def test_save_statement_no_warning_on_new_file():
    """Test that save_statement does not warn when creating a new file."""
    agency = Agency(name="Test Agency", abbr="TEST-NEW", url="https://example.com")

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)

        # No existing file - this is a new statement
        new_data: StatementResult = {
            "title": "New Title",
            "markdown": "# New Content\n\nThis is brand new content.",
            "status_code": 200,
            "final_url": "https://example.com",
            "error": None,
            "source_type": "html",
        }

        from unittest.mock import patch

        with patch("aps_ai_tracker.scraper.logger") as mock_logger:
            result = save_statement(agency, new_data, output_dir)

        # Should save successfully
        assert result == "saved"

        # Should NOT have logged a shrinkage warning
        warning_calls = [
            call
            for call in mock_logger.warning.call_args_list
            if "CONTENT SHRINKAGE" in str(call)
        ]
        assert len(warning_calls) == 0


def test_content_shrinkage_threshold_is_reasonable():
    """Test that the shrinkage threshold is set to a reasonable value."""
    # Threshold should be between 0 and 1
    assert 0 < CONTENT_SHRINKAGE_THRESHOLD < 1

    # Default of 0.5 means warn if content drops below 50% of original
    assert CONTENT_SHRINKAGE_THRESHOLD == 0.5


def test_atomic_write_text_writes_and_cleans_up():
    """atomic_write_text replaces the target in place and leaves no temp file."""
    with TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "STATE.md"
        target.write_text("old content", encoding="utf-8")

        atomic_write_text(target, "new content")

        assert target.read_text(encoding="utf-8") == "new content"
        # The staging file must not survive a successful write.
        assert list(Path(tmpdir).iterdir()) == [target]


def test_process_statements_isolates_unexpected_exceptions(monkeypatch):
    """A save that raises unexpectedly is counted as failed, not batch-fatal."""
    from aps_ai_tracker import scraper as scraper_mod

    bad = Agency(name="Bad Agency", abbr="BAD", url="https://example.com/bad")
    good = Agency(name="Good Agency", abbr="GOOD", url="https://example.com/good")
    html = (
        "<html><body><main><h1>AI use</h1>"
        "<p>We use AI carefully. Our AI systems are reviewed.</p>"
        "</main></body></html>"
    )

    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir) / "raw"
        output_dir = Path(tmpdir) / "statements"
        raw_dir.mkdir()
        for agency in (bad, good):
            (raw_dir / f"{agency.abbr}.html").write_text(html, encoding="utf-8")

        real_save = scraper_mod.save_statement

        def exploding_save(agency, data, output_dir):
            if agency.abbr == "BAD":
                raise RuntimeError("mdformat edge case")
            return real_save(agency, data, output_dir)

        monkeypatch.setattr(scraper_mod, "save_statement", exploding_save)
        # BAD comes first, so a batch-aborting exception would also lose GOOD.
        counts = process_statements([bad, good], raw_dir, output_dir)

        assert counts == ProcessCounts(saved=1, warned=0, failed=1)
        assert (output_dir / "GOOD.md").exists()
        assert not (output_dir / "BAD.md").exists()


def test_process_statements_counts_shrinkage_as_warned():
    """A statement that shrinks past the threshold lands in the warned tally."""
    agency = Agency(name="Test Agency", abbr="SHRINKY", url="https://example.com")
    existing = "\n".join(
        [
            "---",
            "agency: Test Agency",
            "abbr: SHRINKY",
            "source_url: https://example.com",
            "title: Original",
            "---",
            "",
            "# Original content",
            "",
            "A substantial statement about AI use. " * 20,
        ]
    )
    html = "<html><body><main><p>AI. AI.</p></main></body></html>"

    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir) / "raw"
        output_dir = Path(tmpdir) / "statements"
        raw_dir.mkdir()
        output_dir.mkdir()
        (output_dir / "SHRINKY.md").write_text(existing, encoding="utf-8")
        (raw_dir / "SHRINKY.html").write_text(html, encoding="utf-8")

        counts = process_statements([agency], raw_dir, output_dir)

        assert counts == ProcessCounts(saved=0, warned=1, failed=0)


# Tests for expanded boilerplate removal


def test_remove_boilerplate_strips_feedback_forms():
    """Test that feedback forms, aside, and social blocks are stripped."""
    html = """
    <html><body><main>
        <p>AI transparency content</p>
        <form><input type="text"><button>Submit</button></form>
        <aside>Sidebar navigation links</aside>
        <div class="feedback">Was this page helpful?</div>
        <div class="social-share">Share on Facebook</div>
    </main></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    content = extract_main_content(soup)

    assert "AI transparency content" in content
    assert "Submit" not in content
    assert "Sidebar navigation" not in content
    assert "Was this page helpful" not in content
    assert "Share on Facebook" not in content


def test_remove_boilerplate_decodes_cloudflare_email():
    """Cloudflare-obfuscated addresses decode, rather than keeping the placeholder.

    Markup as AIFS serves it: a <span data-cfemail> whose text is the literal
    "[email protected]", wrapped in a link to /cdn-cgi/l/email-protection.
    """
    html = """
    <html><body><main>
        <p>please contact
        <a href="/cdn-cgi/l/email-protection#2948406948404f5a074e465f07485c"><span
           class="__cf_email__"
           data-cfemail="95f4fcd5f4fcf3e6bbf2fae3bbf4e0">[email&#160;protected]</span></a>.</p>
    </main></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    content = extract_main_content(soup)

    assert "ai@aifs.gov.au" in content
    assert "email" not in content or "protected" not in content
    assert "cdn-cgi" not in content


def test_decode_cf_email_rejects_non_hashes():
    """A malformed or non-email hash decodes to None so the text is kept as-is."""
    assert decode_cf_email("95f4fcd5f4fcf3e6bbf2fae3bbf4e0") == "ai@aifs.gov.au"
    assert decode_cf_email("") is None
    assert decode_cf_email("zz") is None
    assert decode_cf_email("95") is None
    # Decodes cleanly but holds no address, so it isn't an obfuscated email.
    assert decode_cf_email("0068690a") is None


def test_remove_boilerplate_keeps_text_when_hash_is_undecodable():
    """An undecodable hash falls back to the old behaviour: keep the link text."""
    html = """
    <html><body><main>
        <p>contact <span data-cfemail="nothexatall">the AI team</span>.</p>
    </main></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    content = extract_main_content(soup)

    assert "the AI team" in content


def test_remove_boilerplate_strips_related_content_blocks():
    """Rotating 'related content' CTA card blocks churn the diff; strip them."""
    html = """
    <html><body><main>
        <p>AI transparency content</p>
        <div class="block block-inline-blockblock-cta-loosely-related-auto">
            <h3><a href="/learn">Learn</a></h3>
            <p>Driven by an inquiry approach.</p>
        </div>
    </main></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    content = extract_main_content(soup)

    assert "AI transparency content" in content
    assert "Learn" not in content
    assert "inquiry approach" not in content


def test_remove_boilerplate_strips_bare_carousel():
    """Decorative card carousels churn their tiles per render; strip them even
    when not wrapped in a 'related content' block (cf. MoAD's, which are)."""
    html = """
    <html><body><main>
        <p>AI transparency content</p>
        <div class="carousel-wrapper carousel-exhibitions">
            <div class="carousel-cell"><h3><a href="/venue-hire">Venue hire</a></h3>
                <p>Plan your next event at Old Parliament House.</p></div>
            <div class="carousel-cell"><h3><a href="/learn">Learn</a></h3>
                <p>Driven by an inquiry approach.</p></div>
        </div>
    </main></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    content = extract_main_content(soup)

    assert "AI transparency content" in content
    assert "Venue hire" not in content
    assert "inquiry approach" not in content


def test_remove_boilerplate_strips_anchor_jump_menu():
    """A loose mobile 'jump to section' anchor menu leaks its heading as nav
    chrome; strip it (ACSQHC's 'Go to section' toggle)."""
    html = """
    <html><body><main>
        <p>AI transparency content</p>
        <div class="mobile-anchor-nav-container">
            <button class="mobile-anchor-toggle"><h3>Go to section</h3></button>
        </div>
    </main></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    content = extract_main_content(soup)

    assert "AI transparency content" in content
    assert "Go to section" not in content


def test_remove_boilerplate_strips_script_style():
    """Test that script, style, and noscript tags are stripped."""
    html = """
    <html><body><main>
        <p>Real content</p>
        <script>var x = 1;</script>
        <style>.foo { color: red; }</style>
        <noscript>Enable JavaScript</noscript>
    </main></body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    content = extract_main_content(soup)

    assert "Real content" in content
    assert "var x" not in content
    assert ".foo" not in content
    assert "Enable JavaScript" not in content


# Tests for clean_markdown


def test_clean_markdown_strips_last_reviewed_dates():
    """Test that date stamp lines are removed from markdown."""
    text = (
        "# AI Statement\n\n"
        "We use AI responsibly.\n\n"
        "This statement was last reviewed on 15 January 2025.\n\n"
        "More content here.\n"
    )
    result = clean_markdown(text)

    assert "AI Statement" in result
    assert "We use AI responsibly" in result
    assert "More content here" in result
    assert "last reviewed" not in result


def test_clean_markdown_strips_various_date_formats():
    """Test multiple date line formats are stripped."""
    cases = [
        "Last updated: 3 March 2025\n",
        "Date published: 12 June 2024\n",
        "Page last updated 1 February 2025\n",
        "Last modified on 22 December 2024\n",
    ]
    for line in cases:
        result = clean_markdown(f"Content before.\n\n{line}\nContent after.")
        assert "Content before" in result
        assert "Content after" in result
        assert "202" not in result, f"Date line not stripped: {line!r}"


def test_clean_markdown_strips_relative_date_counters():
    """Relative 'last reviewed N ago' counters tick over every scrape; strip them."""
    cases = [
        "Page last reviewed: **1 months ago**\n",
        "Page last reviewed: **28 days ago**\n",
        "Page last reviewed: **3 hours ago**\n",
        "Last updated 2 weeks ago\n",
        "Page last reviewed: yesterday\n",
    ]
    for line in cases:
        result = clean_markdown(f"Content before.\n\n{line}\nContent after.")
        assert "Content before" in result
        assert "Content after" in result
        assert "ago" not in result and "yesterday" not in result, (
            f"Relative date line not stripped: {line!r}"
        )


def test_clean_markdown_strips_inline_date_keeps_preceding_sentence():
    """An inline date stamp sharing a paragraph with real prose must lose only
    the stamp sentence, not the sentence before it (ACSQHC regression)."""
    text = (
        "We will update this transparency statement as the Commission develops "
        "policies. This transparency statement was last updated on 20 February 2026."
    )
    result = clean_markdown(text)

    assert (
        "We will update this transparency statement as the Commission develops policies."
        in result
    )
    assert "20 February 2026" not in result
    assert "last updated" not in result


def test_clean_markdown_strips_leading_date_keeps_following_sentence():
    """A date stamp that leads a line, with real prose after, must lose only the
    stamp (DEWR regression)."""
    text = (
        "This AI Transparency Statement was last updated on 27 February 2026. "
        "It will be reviewed and updated annually or when significant changes occur."
    )
    result = clean_markdown(text)

    assert (
        "It will be reviewed and updated annually or when significant changes occur."
        in result
    )
    assert "27 February 2026" not in result
    assert "last updated" not in result


def test_clean_markdown_does_not_truncate_metadata_link_row():
    """A whole-line metadata row with links must be cleared entirely, not cut
    mid-URL (ATSB regression)."""
    text = (
        "Real AI statement content.\n\n"
        "**First published:** [March 2025](https://www.example.gov.au/a) "
        "**Last updated:** [20 February 2026](https://www.example.gov.au/b)\n\n"
        "More content."
    )
    result = clean_markdown(text)

    assert "Real AI statement content" in result
    assert "More content" in result
    assert "First published" not in result
    assert "example.gov.au/a" not in result, "metadata row truncated mid-URL"


def test_clean_markdown_strips_trailing_widgets():
    """Test that feedback and social share boilerplate is stripped."""
    text = (
        "# Statement\n\n"
        "AI content here.\n\n"
        "Did you find this helpful?\n"
        "Facebook Twitter LinkedIn\n"
    )
    result = clean_markdown(text)

    assert "AI content here" in result
    assert "Did you find this helpful" not in result
    assert "Facebook Twitter LinkedIn" not in result


def test_clean_markdown_strips_share_widgets():
    """Share-widget chrome — endpoint links in any wrapper, plus the orphan
    'Share' label — is stripped, in each of the shapes seen in the corpus
    (AIFS, AIHW, APSC, DISR regressions)."""
    text = (
        "AI content here.\n\n"
        "Share\n\n"
        '[ ](https://www.facebook.com/sharer/sharer.php?u=x "Share to Facebook")\n\n'
        "- [Linkedin](http://www.linkedin.com/shareArticle?mini=true&url=x)\n"
        "- [Twitter](http://twitter.com/intent/tweet?status=x)\n\n"
        "[ Share via Facebook ](https://www.facebook.com/sharer/sharer.php?u=x) "
        "Share via email\n"
    )
    result = clean_markdown(text)
    assert result == "AI content here."

    prose = "We share information about our AI use with the public."
    assert clean_markdown(prose) == prose


def test_clean_markdown_strips_invisible_characters():
    """Zero-width spaces and soft hyphens render as nothing but differ between
    capture routes, so they are removed (ACIAR regression). Emoji joiners stay."""
    text = "Co-\u200boperation with the Depart\u00adment.\n\nFamily: \U0001f469\u200d\U0001f467"
    assert clean_markdown(text) == (
        "Co-operation with the Department.\n\nFamily: \U0001f469\u200d\U0001f467"
    )


def test_clean_markdown_strips_link_affixes():
    """CMS screen-reader affixes glued to link labels are stripped: the
    parenthesised form, the AIHW dash form, and Drupal's extlink label
    (NBA, AIHW, PMC regressions)."""
    text = (
        "Read the [DTA policy(Opens in a new tab/window)](https://x.gov.au/a), "
        "the _[Privacy Act 1988 - external site opens in new window](https://x.gov.au/b)_ "
        "and [Australia\u2019s AI Ethics Principles(link is external)](https://x.gov.au/c)."
    )
    result = clean_markdown(text)
    assert result == (
        "Read the [DTA policy](https://x.gov.au/a), "
        "the _[Privacy Act 1988](https://x.gov.au/b)_ "
        "and [Australia\u2019s AI Ethics Principles](https://x.gov.au/c)."
    )


def test_format_markdown_repairs_malformed_tables():
    """Tables whose colspan'd (or missing) header disagrees with the delimiter
    are repaired to parse as GFM — header padded or synthesised, delimiter
    widened to the widest row (SENATE, SIA, NCC regressions)."""
    from aps_ai_tracker.scraper import format_markdown

    # colspan'd title row over a wider body (SENATE shape)
    senate = (
        "| Usage patterns  \n---|---  \n"
        "Domains | Decision making | Analytics | Productivity  \n"
        "Service delivery | | Internal use | Internal use\n"
    )
    out = format_markdown(senate)
    assert "| ---" in out and "\\" not in out

    # headerless table (SIA shape)
    sia = "---|---  \nAccountable Official | Compliant  \nAI Transparency Statement | Compliant\n"
    out = format_markdown(sia)
    assert "| ---" in out and "\\" not in out
    assert "Accountable Official" in out

    # one-cell header over two-cell rows (NCC shape)
    ncc = "| **Summary of Expenditure**  \n---|---  \n| Total value of briefs| $0  \n| Total fees paid| $0\n"
    out = format_markdown(ncc)
    assert "| ---" in out and "\\" not in out


def test_format_markdown_keeps_tables():
    """html2text's pipe tables must survive mdformat as GFM tables — without the
    gfm extension they collapse into a `---|---\\` paragraph (NBA regression)."""
    from aps_ai_tracker.scraper import format_markdown

    text = "Domain| Description  \n---|---  \nService delivery| Better services.  \n"
    result = format_markdown(text)
    assert "\\" not in result
    assert "| Domain" in result
    assert "| ---" in result


def test_clean_markdown_strips_on_this_page_toc_labels():
    """Orphan 'on this page' table-of-contents labels (in any wrapper) are nav,
    not content, and must be stripped — but prose that merely contains the phrase
    must survive (MOADOPH regression)."""
    labels = [
        "## On this page",
        "### On this page:",
        "##### On this page",
        "**On this page:**",
        "On this page",
        "- ## On this page",
    ]
    for label in labels:
        result = clean_markdown(
            f"# AI use\n\n{label}\n\n## How we use AI\n\nWe use AI."
        )
        assert "On this page" not in result, f"label not stripped: {label!r}"
        assert "How we use AI" in result

    prose = "The content on this page aligns with the DTA policy on AI use."
    assert clean_markdown(prose) == prose


def test_clean_markdown_strips_on_this_page_with_jump_list():
    """When the 'on this page' jump-link list survives html2text, the whole
    table of contents (label + list) is stripped, not just the label — otherwise
    mdformat mangles the orphan list (AUSTRAC regression)."""
    text = (
        "# Our AI statement\n\n"
        "## On this page\n\n"
        "- Introduction\n"
        "- How we use AI\n"
        "- Contact information\n\n"
        "## Introduction\n\n"
        "We use AI to detect financial crime.\n"
    )
    result = clean_markdown(text)
    assert "On this page" not in result
    assert "- Introduction" not in result
    assert "- How we use AI" not in result
    assert "## Introduction" in result
    assert "We use AI to detect financial crime." in result


def test_clean_markdown_strips_back_to_top_and_skip_links():
    """'Back to top' (repeated per section) and 'skip to' links are navigation."""
    nav_lines = [
        "Back to top",
        "BACK TO TOP",
        "Go back to top",
        "Back to top of the page",
        "[Back to top](https://example.gov.au/statement)",
        "Skip to content or footer",
        "Skip to the content",
        "Skip to page navigation",
    ]
    for line in nav_lines:
        result = clean_markdown(f"AI content before.\n\n{line}\n\nAI content after.")
        assert "AI content before" in result
        assert "AI content after" in result
        assert "top" not in result.lower() and "skip to" not in result.lower(), (
            f"nav line not stripped: {line!r}"
        )


def test_clean_markdown_strips_empty_headings():
    """A heading emptied of its text (icon/link stripped upstream) is noise."""
    text = "# AI use\n\n### \n\nWe use AI responsibly.\n\n## \n\nMore detail."
    result = clean_markdown(text)
    assert "We use AI responsibly" in result
    assert "More detail" in result
    assert not re.search(r"(?m)^#{1,6}\s*$", result), "empty heading survived"


def test_clean_markdown_preserves_clean_content():
    """Test that clean content passes through unchanged."""
    text = "# AI Transparency\n\nWe use AI to improve services."
    result = clean_markdown(text)
    assert result == text


# Tests for AI keyword density warning


def test_save_statement_warns_on_low_ai_keywords(caplog):
    """Test warning when content lacks AI-related keywords."""
    agency = Agency(name="Test Agency", abbr="TEST-NOAI", url="https://example.com")

    data: StatementResult = {
        "title": "Governance Statement",
        "markdown": "# Governance\n\nThis is about our general governance framework.",
        "status_code": 200,
        "final_url": "https://example.com",
        "error": None,
        "source_type": "html",
    }

    with TemporaryDirectory() as tmpdir:
        import logging

        with caplog.at_level(logging.WARNING):
            save_statement(agency, data, Path(tmpdir))

        assert any("LOW AI KEYWORD DENSITY" in r.message for r in caplog.records)
        assert any("TEST-NOAI" in r.message for r in caplog.records)


def test_save_statement_no_warning_with_sufficient_ai_keywords(caplog):
    """Test no warning when content has enough AI-related keywords."""
    agency = Agency(name="Test Agency", abbr="TEST-HASAI", url="https://example.com")

    data: StatementResult = {
        "title": "AI Transparency Statement",
        "markdown": (
            "# AI Transparency Statement\n\n"
            "We use AI to improve services. Our AI systems are governed by "
            "the artificial intelligence ethics framework."
        ),
        "status_code": 200,
        "final_url": "https://example.com",
        "error": None,
        "source_type": "html",
    }

    with TemporaryDirectory() as tmpdir:
        import logging

        with caplog.at_level(logging.WARNING):
            save_statement(agency, data, Path(tmpdir))

        assert not any("LOW AI KEYWORD DENSITY" in r.message for r in caplog.records)


def test_inline_page_schema_recovers_client_rendered_sections():
    """SharePoint page-schema pages hold the statement body in a hidden field."""
    from aps_ai_tracker.scraper import extract_main_content, inline_page_schema

    payload = json.dumps(
        {
            "content": [
                {
                    "text": "AI governance",
                    "block": "<p>The CDO is the Accountable Official.</p>",
                },
                {"text": "", "block": "<ul><li>no heading</li></ul>"},
            ]
        }
    )
    html = (
        "<html><body><main><h1>AI Transparency Statement</h1><p>Intro.</p>"
        f'<input type="hidden" name="ctl00$PlaceHolderMain$PageSchemaHiddenField$Input" value="{escape(payload)}">'
        "</main></body></html>"
    )
    soup = BeautifulSoup(html, "lxml")
    assert inline_page_schema(soup) == 2
    content = extract_main_content(soup)
    assert "<h2>AI governance</h2>" in content
    assert "Accountable Official" in content
    assert "no heading" in content
    # no such field: nothing inlined, content untouched
    plain = BeautifulSoup(
        "<html><body><main><p>Just intro.</p></main></body></html>", "lxml"
    )
    assert inline_page_schema(plain) == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "This transparency statement was last updated on 25 February 2026.",
            "25 February 2026",
        ),
        (
            "**Last updated:** [20 February 2026](https://www.example.gov.au/b)",
            "20 February 2026",
        ),
        ("Last reviewed: March 2026", "March 2026"),
        ("Page last updated 1st May 2026", "1st May 2026"),
        ("Last updated 12/03/2026", "12/03/2026"),
        ("Page last reviewed: 3 days ago", None),
        ("No stamp at all.", None),
    ],
)
def test_extract_last_updated_reads_the_pages_own_date(text, expected):
    from aps_ai_tracker.scraper import extract_last_updated

    assert extract_last_updated(text) == expected


# Tests for the manual-agency staleness check


def _manual(abbr: str, last_verified: str | None) -> Agency:
    return Agency(
        name=f"Agency {abbr}",
        abbr=abbr,
        url="https://example.gov.au/ai",
        manual=True,
        manual_reason="blocked",
        last_verified=last_verified,
    )


def test_overdue_flags_never_verified_and_stale():
    """Never-verified and past-interval agencies are due; recent ones are not."""
    today = date(2026, 9, 1)
    agencies = [
        _manual("NEVER", None),
        _manual("STALE", "2026-07-01"),
        _manual("FRESH", "2026-08-25"),
        # Exactly on the boundary: 30 days old counts as due, so a monthly
        # rhythm doesn't drift a day later on every pass.
        _manual("EDGE", "2026-08-02"),
        Agency(name="Auto", abbr="AUTO", url="https://example.gov.au/ai"),
    ]

    assert [a.abbr for a in overdue(agencies, today)] == ["NEVER", "STALE", "EDGE"]


def test_overdue_ignores_automated_agencies():
    """An agency the scraper still fetches is never a hand-check candidate."""
    agencies = [Agency(name="Auto", abbr="AUTO", url="https://example.gov.au/ai")]

    assert overdue(agencies, date(2026, 9, 1)) == []


def test_every_manual_agency_is_reachable_by_the_check():
    """The real corpus: each manual agency either has a date or is flagged now."""
    manual = [a for a in load_agencies() if a.manual]
    due = overdue(load_agencies(), datetime.now(UTC).date())

    assert manual, "expected some manual agencies"
    for agency in manual:
        assert agency.last_verified is not None or agency in due


# Tests for the browser fetch path


def _fake_browser(script: list[tuple[int, str, str]]):
    """A BrowserRunner replaying `script`, recording the argv it was given."""
    calls: list[list[str]] = []

    def runner(args: list[str]) -> tuple[int, str, str]:
        calls.append(args)
        # `close` in the finally block runs after the script is exhausted.
        return script.pop(0) if script else (0, "", "")

    return runner, calls


def test_fetch_raw_browser_wraps_the_captured_html():
    """The CLI returns the <html> element's inner HTML, so the doctype and
    wrapper are added back to match the shape the httpx path saves."""
    agency = Agency(name="Dept", abbr="PMC", url="https://x.gov.au/ai")
    runner, calls = _fake_browser(
        [
            (0, "", ""),  # open
            (0, "<head><title>AI</title></head><body>Statement.</body>", ""),
            (0, "https://x.gov.au/ai-final\n", ""),  # get url
        ]
    )

    result = fetch_raw_browser(agency, runner=runner, retry_delay=0)

    assert result["error"] is None
    assert result["content"] is not None
    body = result["content"].decode("utf-8")
    assert body.startswith('<!DOCTYPE html><html lang="en">')
    assert body.endswith("</html>")
    assert "Statement." in body
    assert result["final_url"] == "https://x.gov.au/ai-final"
    assert result["content_type"] == "text/html; charset=utf-8"
    assert calls[-1][0] == "close", "the browser session is always closed"


def test_fetch_raw_browser_retries_a_challenge_then_succeeds():
    """The first load of a challenged page often is the challenge itself; the
    reload carries the clearance cookie it just set."""
    agency = Agency(name="Dept", abbr="PMC", url="https://x.gov.au/ai")
    runner, _ = _fake_browser(
        [
            (0, "", ""),
            (0, "<head><title>Just a moment...</title></head><body></body>", ""),
            (0, "", ""),
            (0, "<body>The real statement.</body>", ""),
            (0, "https://x.gov.au/ai", ""),
        ]
    )

    result = fetch_raw_browser(agency, runner=runner, retry_delay=0)

    assert result["error"] is None
    assert result["content"] is not None
    assert "The real statement." in result["content"].decode("utf-8")


def test_fetch_raw_browser_gives_up_on_a_persistent_challenge():
    """A challenge that survives the reload is a failed fetch, not content:
    saving it would overwrite the statement with an interstitial."""
    agency = Agency(name="Dept", abbr="PMC", url="https://x.gov.au/ai")
    challenge = (0, "<title>Attention Required! | Cloudflare</title>", "")
    runner, _ = _fake_browser([(0, "", ""), challenge, (0, "", ""), challenge])

    result = fetch_raw_browser(agency, runner=runner, retry_delay=0)

    assert result["content"] is None
    assert result["error"] is not None
    assert "challenge" in result["error"]


def test_fetch_raw_browser_reports_a_missing_cli():
    """A machine without agent-browser fails the fetch cleanly rather than
    raising through the run."""
    agency = Agency(name="Dept", abbr="PMC", url="https://x.gov.au/ai")

    def runner(args: list[str]) -> tuple[int, str, str]:
        raise FileNotFoundError("agent-browser")

    result = fetch_raw_browser(agency, runner=runner, retry_delay=0)

    assert result["content"] is None
    assert result["error"] is not None
    assert "not installed" in result["error"]
