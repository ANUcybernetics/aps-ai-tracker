"""Core scraping functionality for AI transparency statements."""

import asyncio
import hashlib
import json
import logging
import random
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

import html2text
import httpx
import mdformat
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

AI_KEYWORD_RE = re.compile(r"(?i)\bAI\b|artificial intelligence")
AI_KEYWORD_MIN_COUNT = 2

# Government-site WAFs (Cloudflare, CloudFront) block unrecognised User-Agents
# and challenge bursts of bot-like traffic. A realistic browser identity plus
# gentle, jittered concurrency keeps the daily scrape under the bot radar: the
# old "AU-Gov-AI-Transparency-Tracker/1.0" UA was returning 403 outright (e.g.
# MDBA), and firing every request at once tripped per-IP rate limiters, which is
# what produced the rotating 403s in the scrape logs.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/pdf,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-AU,en;q=0.9",
}

# Keep concurrent fetches low so the run doesn't look like a burst to per-IP
# limiters (a shared Cloudflare reputation spans many of these gov domains).
MAX_CONCURRENT_FETCHES = 3

# Statuses worth retrying: rate-limiting and transient WAF blocks (403, 429)
# plus 5xx. 403 is included because gov WAFs return it for burst throttling, not
# only genuine "forbidden"; 401/404/410 are never retried.
RETRYABLE_STATUS_CODES = frozenset({403, 408, 425, 429, 500, 502, 503, 504})


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
    source_type: Literal["html", "pdf"] | None


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


def extract_frontmatter(filepath: Path) -> dict | None:
    """Parse the YAML frontmatter from a statement file."""
    if not filepath.exists():
        return None
    try:
        content = filepath.read_text(encoding="utf-8")
        parts = content.split("---\n", 2)
        if len(parts) >= 3:
            return yaml.safe_load(parts[1]) or {}
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


_LAST_REVIEWED_RE = re.compile(
    r"(?m)^.*(?:last (?:reviewed|updated|modified)|date (?:published|modified)|page updated).*\d{1,2}.*\d{4}.*$\n?",
    re.IGNORECASE,
)

_TRAILING_BOILERPLATE_RE = re.compile(
    r"(?mi)^.*(?:did you find this (?:helpful|useful)\??|rate your experience|"
    r"share (?:this|on)\b.*(?:facebook|twitter|linkedin)|"
    r"print this page|email this page|"
    r"\[?\s*(?:facebook|twitter|linkedin|email)\s*\]?\s*\[?\s*(?:facebook|twitter|linkedin|email)\s*\]?).*$\n?",
)

_OFFICIAL_MARKER_RE = re.compile(
    r"(?im)^\s*(?:classification:\s*)?official(?:\s*[-:]\s*sensitive)?\s*$\n?"
)

_ALSO_INTERESTED_RE = re.compile(
    r"(?ims)^#{1,6}\s*you may also be interested in.*?(?=^#{1,6}\s|\Z)"
)


def clean_markdown(text: str) -> str:
    """Strip date stamps, classification markers, and trailing boilerplate."""
    text = _LAST_REVIEWED_RE.sub("", text)
    text = _TRAILING_BOILERPLATE_RE.sub("", text)
    text = _OFFICIAL_MARKER_RE.sub("", text)
    text = _ALSO_INTERESTED_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def format_markdown(text: str) -> str:
    """Apply deterministic markdown formatting to reduce diff variance."""
    return mdformat.text(text).strip()


def remove_boilerplate(element: BeautifulSoup) -> None:
    """Remove common boilerplate elements from HTML."""
    boilerplate_selectors = [
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "script",
        "style",
        "noscript",
        "[role='navigation']",
        "[role='banner']",
        "[role='contentinfo']",
        "[role='complementary']",
        "[role='form']",
        ".breadcrumb",
        ".breadcrumbs",
        ".navigation",
        ".nav",
        ".sidebar",
        ".site-header",
        ".site-footer",
        ".page-header",
        ".page-footer",
        ".feedback",
        ".share",
        ".social-share",
        ".social-links",
        ".social-media",
        ".subscribe",
        ".newsletter",
        ".alert",
        ".alert-banner",
        ".banner",
        ".notification",
        ".notice-banner",
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


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Server's Retry-After hint in seconds (capped), if given as an integer."""
    value = response.headers.get("retry-after", "")
    return min(float(value), 30.0) if value.isdigit() else None


def _backoff_delay(attempt: int, retry_after: float | None) -> float:
    """Exponential backoff with jitter, honouring a server Retry-After hint."""
    if retry_after is not None:
        return retry_after + random.uniform(0, 1.0)
    return 2.0**attempt + random.uniform(0, 1.5)


async def fetch_raw_async(
    agency: Agency, client: httpx.AsyncClient, max_retries: int = 4
) -> RawFetchResult:
    """Fetch raw content (HTML or PDF) without processing.

    Retries on timeouts, connection errors, and transient HTTP statuses
    (rate-limiting and WAF blocks in RETRYABLE_STATUS_CODES) with exponential
    backoff and jitter, honouring a server Retry-After hint when present.
    """
    if agency.url is None:
        return {
            "content": None,
            "content_type": None,
            "status_code": None,
            "final_url": None,
            "error": "No URL provided",
        }

    # Spread request start times so the run doesn't hit WAFs as one burst.
    await asyncio.sleep(random.uniform(0, 1.5))

    last_error: Exception | None = None
    retry_after: float | None = None

    for attempt in range(max_retries):
        if attempt > 0:
            delay = _backoff_delay(attempt, retry_after)
            retry_after = None
            logger.info(
                f"Retry {attempt}/{max_retries - 1} for {agency.name} after {delay:.1f}s..."
            )
            await asyncio.sleep(delay)

        try:
            logger.info(f"Fetching raw content for {agency.name}...")
            response = await client.get(
                agency.url,
                follow_redirects=True,
                timeout=60.0,
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
            last_error = e
            status = e.response.status_code
            if status in RETRYABLE_STATUS_CODES and attempt < max_retries - 1:
                retry_after = _retry_after_seconds(e.response)
                logger.warning(
                    f"HTTP {status} fetching {agency.name} "
                    f"(attempt {attempt + 1}/{max_retries}); will retry"
                )
                continue
            logger.error(f"HTTP error fetching {agency.name}: {e}")
            return {
                "content": None,
                "content_type": None,
                "status_code": status,
                "final_url": agency.url,
                "error": str(e),
            }
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_error = e
            error_type = type(e).__name__
            logger.warning(
                f"{error_type} fetching {agency.name} (attempt {attempt + 1}/{max_retries})"
            )
            continue
        except Exception as e:
            logger.error(f"Error fetching {agency.name}: {type(e).__name__}: {e}")
            return {
                "content": None,
                "content_type": None,
                "status_code": None,
                "final_url": agency.url,
                "error": f"{type(e).__name__}: {e}",
            }

    # Retries exhausted on the final attempt (a timeout/connect error, since
    # retryable statuses on the last attempt return directly above).
    status_code = (
        last_error.response.status_code
        if isinstance(last_error, httpx.HTTPStatusError)
        else None
    )
    logger.error(
        f"Failed to fetch {agency.name} after {max_retries} attempts: "
        f"{type(last_error).__name__}"
    )
    return {
        "content": None,
        "content_type": None,
        "status_code": status_code,
        "final_url": agency.url,
        "error": f"{type(last_error).__name__}: {last_error}"
        if last_error
        else "Unknown error",
    }


def save_raw(agency: Agency, data: RawFetchResult, raw_dir: Path) -> bool:
    """Save raw content and metadata to files."""
    if data["error"] or not data["content"]:
        logger.warning(f"Skipping {agency.abbr} due to fetch error")
        return False

    raw_dir.mkdir(parents=True, exist_ok=True)

    is_pdf = "application/pdf" in (data["content_type"] or "")
    extension = "pdf" if is_pdf else "html"
    filepath = raw_dir / f"{agency.abbr}.{extension}"
    stale = raw_dir / f"{agency.abbr}.{'html' if is_pdf else 'pdf'}"
    stale.unlink(missing_ok=True)

    filepath.write_bytes(data["content"])

    meta = {"final_url": data["final_url"], "content_type": data["content_type"]}
    (raw_dir / f"{agency.abbr}.meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )

    logger.info(f"Saved raw content to {agency.abbr}.{extension}")
    return True


def _load_raw_meta(agency: Agency, raw_dir: Path) -> dict[str, str | None]:
    """Load metadata saved alongside a raw file."""
    meta_path = raw_dir / f"{agency.abbr}.meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {"final_url": agency.url, "content_type": None}


def process_raw(agency: Agency, raw_dir: Path) -> StatementResult:
    """Process raw content from file into markdown."""
    logger.info(f"Processing raw content for {agency.name}...")

    meta = _load_raw_meta(agency, raw_dir)
    final_url = meta["final_url"] or agency.url

    pdf_path = raw_dir / f"{agency.abbr}.pdf"
    html_path = raw_dir / f"{agency.abbr}.html"

    if pdf_path.exists():
        try:
            pdf_reader = PdfReader(pdf_path)
            raw_title = pdf_reader.metadata.title if pdf_reader.metadata else None
            title = str(raw_title) if raw_title else None
            raw_text = "\n\n".join(
                page.extract_text() for page in pdf_reader.pages
            ).strip()

            return {
                "title": title,
                "markdown": raw_text or None,
                "status_code": 200,
                "final_url": final_url,
                "error": None,
                "source_type": "pdf",
            }
        except Exception as e:
            logger.error(f"Error processing PDF for {agency.name}: {e}")
            return {
                "title": None,
                "markdown": None,
                "status_code": None,
                "final_url": final_url,
                "error": str(e),
                "source_type": "pdf",
            }
    elif html_path.exists():
        try:
            html_content = html_path.read_text(encoding="utf-8")
            soup = BeautifulSoup(html_content, "lxml")
            title = (
                soup.title.string.strip() if soup.title and soup.title.string else None
            )
            if not title and (h1 := soup.find("h1")):
                title = h1.get_text(strip=True)
            markdown = clean_markdown(
                clean_html_to_markdown(
                    extract_main_content(soup, agency.selector), agency.url or ""
                )
            )

            return {
                "title": title,
                "markdown": markdown or None,
                "status_code": 200,
                "final_url": final_url,
                "error": None,
                "source_type": "html",
            }
        except Exception as e:
            logger.error(f"Error processing HTML for {agency.name}: {e}")
            return {
                "title": None,
                "markdown": None,
                "status_code": None,
                "final_url": final_url,
                "error": str(e),
                "source_type": "html",
            }
    else:
        return {
            "title": None,
            "markdown": None,
            "status_code": None,
            "final_url": final_url,
            "error": f"No raw file found for {agency.abbr}",
            "source_type": None,
        }


def save_statement(agency: Agency, data: StatementResult, output_dir: Path) -> bool:
    """Save statement as markdown file with YAML frontmatter.

    For HTML sources, applies markdown cleanup + mdformat and writes the result.
    For PDF sources, writes the raw extracted text plus a `raw_hash` field; the
    actual cleanup is performed by the scrape skill in a separate step. If the
    PDF's raw text is unchanged from the last save (matching `raw_hash`), the
    write is skipped entirely so cleaned bodies aren't clobbered.
    """
    if data["error"] or not data["markdown"]:
        logger.warning(f"Skipping {agency.abbr} due to fetch error")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"{agency.abbr}.md"
    is_pdf = data["source_type"] == "pdf"

    if is_pdf:
        new_body = data["markdown"]
        new_raw_hash = hashlib.sha256(new_body.encode("utf-8")).hexdigest()
        existing = extract_frontmatter(filepath) or {}
        if existing.get("raw_hash") == new_raw_hash:
            logger.info(
                f"Skipping {agency.abbr}: PDF unchanged (raw_hash match)"
            )
            return True
    else:
        new_body = format_markdown(data["markdown"])
        new_raw_hash = None

    existing_markdown = extract_markdown_from_statement(filepath)
    if existing_markdown is not None and not is_pdf:
        old_len = len(existing_markdown)
        new_len = len(new_body)
        if old_len > 0 and new_len < old_len * CONTENT_SHRINKAGE_THRESHOLD:
            shrinkage_pct = (1 - new_len / old_len) * 100
            logger.warning(
                f"CONTENT SHRINKAGE DETECTED for {agency.abbr}: "
                f"content reduced by {shrinkage_pct:.0f}% "
                f"({old_len} -> {new_len} chars). "
                f"This may indicate a scraping failure."
            )

    if len(AI_KEYWORD_RE.findall(new_body)) < AI_KEYWORD_MIN_COUNT:
        logger.warning(
            f"LOW AI KEYWORD DENSITY for {agency.abbr}: "
            f"content may not be an AI transparency statement."
        )

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
    if is_pdf:
        frontmatter["raw_hash"] = new_raw_hash

    yaml_str = yaml.dump(
        frontmatter, default_flow_style=False, allow_unicode=True
    ).strip()
    content = "\n".join(["---", yaml_str, "---", "", new_body])

    filepath.write_text(content, encoding="utf-8")
    logger.info(f"Saved {agency.abbr}.md")
    return True


async def fetch_all_raw(
    agencies: list[Agency],
) -> list[tuple[Agency, RawFetchResult]]:
    """Fetch all raw content with limited concurrency."""
    async with httpx.AsyncClient(
        headers=BROWSER_HEADERS,
        limits=httpx.Limits(
            max_connections=MAX_CONCURRENT_FETCHES,
            max_keepalive_connections=MAX_CONCURRENT_FETCHES,
        ),
    ) as client:
        agencies_with_urls = [a for a in agencies if a.url is not None]

        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(fetch_raw_async(agency, client))
                for agency in agencies_with_urls
            ]

        results = [task.result() for task in tasks]
        return list(zip(agencies_with_urls, results))
