"""Core scraping functionality for AI transparency statements."""

import asyncio
import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import html2text
import httpx
import yaml
from bs4 import BeautifulSoup
from pypdf import PdfReader

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Threshold for content shrinkage warning (as a ratio)
# If new content is less than this fraction of old content, warn about possible scraping failure
CONTENT_SHRINKAGE_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class Agency:
    """Represents an Australian Government agency with its AI transparency statement."""

    name: str
    abbr: str
    url: str | None
    manual: bool = False
    selector: str | None = None


class StatementResult(TypedDict):
    """Result of fetching an AI transparency statement."""

    title: str | None
    markdown: str | None
    status_code: int | None
    final_url: str | None
    error: str | None


class RawFetchResult(TypedDict):
    """Result of fetching raw content."""

    content: bytes | None
    content_type: str | None
    status_code: int | None
    final_url: str | None
    error: str | None


def load_agencies() -> list[Agency]:
    """Load agency data from agencies.toml file."""
    toml_path = Path(__file__).parent.parent.parent / "agencies.toml"
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    return [
        Agency(
            name=d["name"],
            abbr=d["abbr"],
            url=d["url"] if d["url"] else None,
            manual=d.get("manual", False),
            selector=d.get("selector"),
        )
        for d in data["agencies"]
    ]


def extract_markdown_from_statement(filepath: Path) -> str | None:
    """Extract just the markdown content from a statement file (excluding frontmatter).

    Returns None if file doesn't exist or can't be parsed.
    """
    if not filepath.exists():
        return None

    try:
        content = filepath.read_text(encoding="utf-8")
        # Split on frontmatter delimiters (---)
        # Format is: ---\nyaml\n---\n\nmarkdown
        parts = content.split("---\n", 2)
        if len(parts) >= 3:
            # parts[0] is empty (before first ---), parts[1] is yaml, parts[2] is markdown
            return parts[2].strip()
        return None
    except Exception:
        return None


def clean_html_to_markdown(html_content: str, base_url: str) -> str:
    """Convert HTML content to clean markdown."""
    h = html2text.HTML2Text()
    h.body_width = 0
    h.baseurl = base_url
    markdown = h.handle(html_content)
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def remove_boilerplate(element: BeautifulSoup) -> None:
    """Remove common boilerplate elements from HTML."""
    boilerplate_selectors = [
        "nav",
        "header",
        "footer",
        "[role='navigation']",
        "[role='banner']",
        "[role='contentinfo']",
        "[role='complementary']",
        ".breadcrumb",
        ".breadcrumbs",
        ".navigation",
        ".nav",
        ".sidebar",
        ".site-header",
        ".site-footer",
        ".page-header",
        ".page-footer",
        "#header",
        "#footer",
        "#sidebar",
    ]

    for selector in boilerplate_selectors:
        for tag in element.select(selector):
            tag.decompose()

    # Remove email protection links (hashes change on every visit)
    # Replace with just the link text
    for link in element.find_all("a", href=re.compile(r"cdn-cgi/l/email-protection")):
        link.replace_with(link.get_text())


def extract_main_content(soup: BeautifulSoup, selector: str | None = None) -> str:
    """Extract the main content from the page, removing navigation and footers.

    Args:
        soup: BeautifulSoup object of the page
        selector: Optional CSS selector to use instead of default list
    """
    if selector:
        if main_content := soup.select_one(selector):
            remove_boilerplate(main_content)
            return str(main_content)
    else:
        for selector in ["main", "article", ".content", "#content", ".main-content"]:
            if main_content := soup.select_one(selector):
                remove_boilerplate(main_content)
                return str(main_content)

    if body := soup.find("body"):
        remove_boilerplate(body)
        return str(body)

    return str(soup)


async def fetch_raw_async(agency: Agency, client: httpx.AsyncClient) -> RawFetchResult:
    """Fetch raw content (HTML or PDF) without processing."""
    logger.info(f"Fetching raw content for {agency.name}...")

    if agency.url is None:
        return {
            "content": None,
            "content_type": None,
            "status_code": None,
            "final_url": None,
            "error": "No URL provided",
        }

    try:
        response = await client.get(
            agency.url,
            follow_redirects=True,
            timeout=30.0,
        )
        response.raise_for_status()

        return {
            "content": response.content,
            "content_type": response.headers.get("content-type", "").lower(),
            "status_code": response.status_code,
            "final_url": str(response.url),
            "error": None,
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching {agency.name}: {e}")
        return {
            "content": None,
            "content_type": None,
            "status_code": e.response.status_code,
            "final_url": agency.url,
            "error": str(e),
        }
    except Exception as e:
        logger.error(f"Error fetching {agency.name}: {e}")
        return {
            "content": None,
            "content_type": None,
            "status_code": None,
            "final_url": agency.url,
            "error": str(e),
        }


def save_raw(agency: Agency, data: RawFetchResult, raw_dir: Path) -> bool:
    """Save raw content to file."""
    if data["error"] or not data["content"]:
        logger.warning(f"Skipping {agency.abbr} due to fetch error")
        return False

    raw_dir.mkdir(parents=True, exist_ok=True)

    is_pdf = "application/pdf" in (data["content_type"] or "")
    extension = "pdf" if is_pdf else "html"
    filepath = raw_dir / f"{agency.abbr}.{extension}"

    filepath.write_bytes(data["content"])
    logger.info(f"Saved raw content to {agency.abbr}.{extension}")
    return True


def process_raw(agency: Agency, raw_dir: Path) -> StatementResult:
    """Process raw content from file into markdown."""
    logger.info(f"Processing raw content for {agency.name}...")

    pdf_path = raw_dir / f"{agency.abbr}.pdf"
    html_path = raw_dir / f"{agency.abbr}.html"

    if pdf_path.exists():
        try:
            pdf_reader = PdfReader(pdf_path)
            title = pdf_reader.metadata.title if pdf_reader.metadata else None
            markdown = "\n\n".join(page.extract_text() for page in pdf_reader.pages)

            return {
                "title": title,
                "markdown": markdown.strip() if markdown else None,
                "status_code": 200,
                "final_url": agency.url,
                "error": None,
            }
        except Exception as e:
            logger.error(f"Error processing PDF for {agency.name}: {e}")
            return {
                "title": None,
                "markdown": None,
                "status_code": None,
                "final_url": agency.url,
                "error": str(e),
            }
    elif html_path.exists():
        try:
            html_content = html_path.read_text(encoding="utf-8")
            soup = BeautifulSoup(html_content, "lxml")
            title = (
                soup.title.string.strip() if soup.title and soup.title.string else None
            )
            if not title and soup.find("h1"):
                title = soup.find("h1").get_text(strip=True)
            markdown = clean_html_to_markdown(
                extract_main_content(soup, agency.selector), agency.url or ""
            )

            return {
                "title": title,
                "markdown": markdown.strip() if markdown else None,
                "status_code": 200,
                "final_url": agency.url,
                "error": None,
            }
        except Exception as e:
            logger.error(f"Error processing HTML for {agency.name}: {e}")
            return {
                "title": None,
                "markdown": None,
                "status_code": None,
                "final_url": agency.url,
                "error": str(e),
            }
    else:
        return {
            "title": None,
            "markdown": None,
            "status_code": None,
            "final_url": agency.url,
            "error": f"No raw file found for {agency.abbr}",
        }


def save_statement(agency: Agency, data: StatementResult, output_dir: Path) -> bool:
    """Save statement as markdown file with YAML frontmatter.

    Includes a heuristic check for significant content shrinkage, which may
    indicate a scraping failure (e.g., page structure changed, JS didn't render).
    """
    if data["error"] or not data["markdown"]:
        logger.warning(f"Skipping {agency.abbr} due to fetch error")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"{agency.abbr}.md"

    # Check for significant content shrinkage compared to existing file
    new_markdown = str(data["markdown"])
    existing_markdown = extract_markdown_from_statement(filepath)

    if existing_markdown is not None:
        old_len = len(existing_markdown)
        new_len = len(new_markdown)

        if old_len > 0 and new_len < old_len * CONTENT_SHRINKAGE_THRESHOLD:
            shrinkage_pct = (1 - new_len / old_len) * 100
            logger.warning(
                f"CONTENT SHRINKAGE DETECTED for {agency.abbr}: "
                f"content reduced by {shrinkage_pct:.0f}% "
                f"({old_len} -> {new_len} chars). "
                f"This may indicate a scraping failure."
            )

    # Use fallback title if none extracted
    title = (
        data["title"] if data["title"] else f"{agency.abbr} AI Transparency Statement"
    )

    frontmatter = {
        "agency": agency.name,
        "abbr": agency.abbr,
        "source_url": agency.url,
        "title": title,
    }

    if data["final_url"] != agency.url:
        frontmatter["final_url"] = data["final_url"]

    yaml_str = yaml.dump(
        frontmatter, default_flow_style=False, allow_unicode=True
    ).strip()
    content = "\n".join(["---", yaml_str, "---", "", new_markdown])

    filepath.write_text(content, encoding="utf-8")
    logger.info(f"Saved {agency.abbr}.md")
    return True


async def fetch_all_raw(
    agencies: list[Agency],
) -> list[tuple[Agency, RawFetchResult]]:
    """Fetch all raw content in parallel."""
    async with httpx.AsyncClient(
        headers={"User-Agent": "AU-Gov-AI-Transparency-Tracker/1.0"},
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    ) as client:
        agencies_with_urls = [a for a in agencies if a.url is not None]

        async with asyncio.TaskGroup() as tg:  # type: ignore[possibly-missing-attribute]
            tasks = [
                tg.create_task(fetch_raw_async(agency, client))
                for agency in agencies_with_urls
            ]

        results = [task.result() for task in tasks]
        return list(zip(agencies_with_urls, results))
