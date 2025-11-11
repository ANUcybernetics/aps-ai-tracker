"""Core scraping functionality for AI transparency statements."""

import asyncio
import logging
import re
import tomllib
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

import html2text
import httpx
import yaml
from bs4 import BeautifulSoup
from pypdf import PdfReader

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Agency(NamedTuple):
    """Represents an Australian Government agency with its AI transparency statement."""

    name: str
    abbr: str
    url: str | None


def load_agencies() -> list[Agency]:
    """Load agency data from agencies.toml file."""
    toml_path = Path(__file__).parent.parent.parent / "agencies.toml"
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    return [
        Agency(name=d["name"], abbr=d["abbr"], url=d["url"] if d["url"] else None)
        for d in data["agencies"]
    ]


def clean_html_to_markdown(html_content: str, base_url: str) -> str:
    """Convert HTML content to clean markdown."""
    h = html2text.HTML2Text()
    h.body_width = 0
    h.baseurl = base_url
    markdown = h.handle(html_content)
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def extract_main_content(soup: BeautifulSoup) -> str:
    """Extract the main content from the page, removing navigation and footers."""
    for selector in ["main", "article", ".content", "#content", ".main-content"]:
        if main_content := soup.select_one(selector):
            return str(main_content)

    if body := soup.find("body"):
        for tag in body.find_all(["nav", "header", "footer"]):
            tag.decompose()
        return str(body)

    return str(soup)


async def fetch_statement_async(
    agency: Agency, client: httpx.AsyncClient
) -> dict[str, str | int | None]:
    """Fetch and parse an AI transparency statement (async version)."""
    logger.info(f"Fetching {agency.name}...")

    try:
        response = await client.get(
            agency.url,
            follow_redirects=True,
            timeout=30.0,
        )
        response.raise_for_status()

        is_pdf = "application/pdf" in response.headers.get("content-type", "").lower()

        if is_pdf:
            pdf_reader = PdfReader(BytesIO(response.content))
            title = pdf_reader.metadata.title if pdf_reader.metadata else None
            markdown = "\n\n".join(page.extract_text() for page in pdf_reader.pages)
        else:
            soup = BeautifulSoup(response.text, "lxml")
            title = (
                soup.title.string.strip() if soup.title and soup.title.string else None
            )
            if not title and soup.find("h1"):
                title = soup.find("h1").get_text(strip=True)
            markdown = clean_html_to_markdown(extract_main_content(soup), agency.url)

        return {
            "title": title,
            "markdown": markdown.strip() if markdown else None,
            "status_code": response.status_code,
            "final_url": str(response.url),
            "error": None,
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching {agency.name}: {e}")
        return {
            "title": None,
            "markdown": None,
            "status_code": e.response.status_code,
            "final_url": agency.url,
            "error": str(e),
        }
    except Exception as e:
        logger.error(f"Error fetching {agency.name}: {e}")
        return {
            "title": None,
            "markdown": None,
            "status_code": None,
            "final_url": agency.url,
            "error": str(e),
        }


def fetch_statement(agency: Agency) -> dict[str, str | int | None]:
    """Synchronous wrapper for fetch_statement_async (for backwards compatibility)."""

    async def _fetch() -> dict[str, str | int | None]:
        async with httpx.AsyncClient(
            headers={"User-Agent": "AU-Gov-AI-Transparency-Tracker/1.0"},
        ) as client:
            return await fetch_statement_async(agency, client)

    return asyncio.run(_fetch())


def save_statement(
    agency: Agency, data: dict[str, str | int | None], output_dir: Path
) -> bool:
    """Save statement as markdown file with YAML frontmatter."""
    if data["error"] or not data["markdown"]:
        logger.warning(f"Skipping {agency.abbr} due to fetch error")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)

    frontmatter = {
        "agency": agency.name,
        "abbr": agency.abbr,
        "source_url": agency.url,
        "title": data["title"],
    }

    if data["final_url"] != agency.url:
        frontmatter["final_url"] = data["final_url"]

    yaml_str: str = yaml.dump(
        frontmatter, default_flow_style=False, allow_unicode=True
    ).strip()
    markdown_str: str = str(data["markdown"])
    content = "\n".join(["---", yaml_str, "---", "", markdown_str])

    filepath = output_dir / f"{agency.abbr}.md"
    filepath.write_text(content, encoding="utf-8")
    logger.info(f"Saved {agency.abbr}.md")
    return True


async def fetch_all_statements(
    agencies: list[Agency],
) -> list[tuple[Agency, dict[str, str | int | None]]]:
    """Fetch all agency statements in parallel."""
    async with httpx.AsyncClient(
        headers={"User-Agent": "AU-Gov-AI-Transparency-Tracker/1.0"},
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    ) as client:
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(fetch_statement_async(agency, client))
                for agency in agencies
                if agency.url is not None
            ]

        results = [task.result() for task in tasks]
        return list(zip([a for a in agencies if a.url is not None], results))
