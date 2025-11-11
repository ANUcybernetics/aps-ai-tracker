"""
Smoke tests for AI Transparency Statement scraper.

Tests verify basic functionality and invariants without asserting
on external content that may change.

Usage:
    uv run pytest test_scraper.py -v
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml
from bs4 import BeautifulSoup

from aps_ai_transparency_tracker import (
    Agency,
    RawFetchResult,
    StatementResult,
    clean_html_to_markdown,
    extract_main_content,
    fetch_statement,
    load_agencies,
    process_raw,
    save_raw,
    save_statement,
)


def test_agencies_list_structure():
    """Verify agencies list has required structure."""
    agencies = load_agencies()
    assert len(agencies) > 0
    for agency in agencies:
        assert isinstance(agency, Agency)
        assert agency.name
        assert agency.abbr
        assert agency.url is None or agency.url.startswith("http")


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


def test_fetch_statement_returns_required_fields():
    """Test fetch_statement returns dict with all required fields."""
    agencies = load_agencies()
    agency = agencies[0]
    result = fetch_statement(agency)

    required_fields = {"title", "markdown", "status_code", "final_url", "error"}
    assert set(result.keys()) == required_fields


def test_fetch_statement_handles_success():
    """Test successful fetch has expected characteristics."""
    agencies = load_agencies()
    agency = agencies[0]
    result = fetch_statement(agency)

    # Either successful or has error
    if result["error"] is None:
        assert result["status_code"] == 200
        assert result["markdown"] is not None
        markdown_content = result["markdown"]
        assert isinstance(markdown_content, str) and len(markdown_content) > 0
        assert result["final_url"] is not None
    else:
        # If there's an error, status_code might be None or error code
        assert isinstance(result["error"], str)


def test_fetch_statement_type_consistency():
    """Test fetch_statement returns consistent types."""
    agencies = load_agencies()
    agency = agencies[0]
    result = fetch_statement(agency)

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
    }

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        result = save_statement(dept, data, output_dir)

        assert result is True
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


def test_save_statement_handles_error_case():
    """Test save_statement skips file creation when there's an error."""
    dept = Agency(name="Test Agency", abbr="TEST-ERROR", url="https://example.com/test")

    data: StatementResult = {
        "title": None,
        "markdown": None,
        "status_code": 404,
        "final_url": "https://example.com/test",
        "error": "Not found",
    }

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        result = save_statement(dept, data, output_dir)

        # Should return False and not create file
        assert result is False
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
    }

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        result = save_statement(dept, data, output_dir)

        # Should return False and not create file
        assert result is False
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
    }

    with TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        result = save_statement(dept, data, output_dir)

        assert result is True
        filepath = output_dir / "TEST-REDIRECT.md"
        content = filepath.read_text()

        parts = content.split("---\n")
        yaml_content = parts[1]
        metadata = yaml.safe_load(yaml_content)

        # final_url should be present when it differs from source_url
        assert metadata["final_url"] == "https://example.com/new"
        assert metadata["source_url"] == "https://example.com/old"


def test_save_raw_html():
    """Test save_raw saves HTML content correctly."""
    agency = Agency(name="Test Agency", abbr="TEST-HTML", url="https://example.com")

    html_content = b"<html><body><h1>Test</h1></body></html>"
    data: RawFetchResult = {
        "content": html_content,
        "content_type": "text/html; charset=utf-8",
        "status_code": 200,
        "final_url": "https://example.com",
        "error": None,
    }

    with TemporaryDirectory() as tmpdir:
        raw_dir = Path(tmpdir)
        result = save_raw(agency, data, raw_dir)

        assert result is True
        filepath = raw_dir / "TEST-HTML.html"
        assert filepath.exists()
        assert filepath.read_bytes() == html_content


def test_save_raw_pdf():
    """Test save_raw saves PDF content correctly."""
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
        assert result["markdown"] is not None
        markdown_content = result["markdown"]
        assert isinstance(markdown_content, str)
        assert "Test Heading" in markdown_content
        assert "Test paragraph content" in markdown_content


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
@pytest.mark.parametrize(
    "agency",
    [a for a in load_agencies() if a.url is not None],
    ids=lambda a: a.abbr,
)
def test_known_agency_statements_can_be_fetched(agency):
    """Integration test: verify agencies with known URLs can be fetched and parsed.

    Skipped by default. Run with: pytest -m might_fail
    """
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
