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
from typing import Literal, NotRequired, TypedDict

import html2text
import httpx
import mdformat
import yaml
from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# The repo root, resolved from the package location rather than the working
# directory, so every entry point (scrape/process/status/export) reads and
# writes the same tree no matter where it is invoked from. This package is a
# repo-coupled tool (installed editable via uv), so the anchor is reliable.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

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
    size: str = "unknown"
    scope: str = "mandatory"
    portfolio: str | None = None
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
    # The page's own last-updated stamp, read before cleanup strips it.
    last_updated: NotRequired[str | None]


class RawFetchResult(TypedDict):
    """Result of fetching raw content."""

    content: bytes | None
    content_type: str | None
    status_code: int | None
    final_url: str | None
    error: str | None


# Outcome of one save_statement call. "warned" means the file was still written
# (so the diff is reviewable) but the content shrank past
# CONTENT_SHRINKAGE_THRESHOLD — suspicious enough that the run's exit code must
# flag it, because the nightly cron auto-commits whatever lands on disk.
type SaveStatus = Literal["saved", "warned", "failed"]


@dataclass(frozen=True, slots=True)
class ProcessCounts:
    """Stage-2 tallies: saved cleanly / saved with a shrinkage warning / failed."""

    saved: int
    warned: int
    failed: int


def load_agencies() -> list[Agency]:
    """Load agency data from agencies.toml file."""
    with open(REPO_ROOT / "agencies.toml", "rb") as f:
        data = tomllib.load(f)
    return [
        Agency(
            name=d["name"],
            abbr=d["abbr"],
            url=d["url"] if d["url"] else None,
            size=d.get("size", "unknown"),
            scope=d.get("scope", "mandatory"),
            portfolio=d.get("portfolio"),
            manual=d.get("manual", False),
            selector=d.get("selector"),
        )
        for d in data["agencies"]
    ]


def split_frontmatter_body(content: str) -> tuple[dict | None, str]:
    """Split a statement file's text into (frontmatter dict, markdown body).

    Format is: ---\\nyaml\\n---\\n\\nmarkdown. Returns (None, whole text) when the
    text has no frontmatter block. Historical revisions occasionally carry
    non-safe frontmatter (e.g. a PDF title serialised as a pypdf object tag);
    since callers walking history only need the body, an unparseable frontmatter
    degrades to {} rather than failing.
    """
    parts = content.split("---\n", 2)
    if len(parts) >= 3:
        try:
            frontmatter = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            frontmatter = {}
        return (frontmatter, parts[2].strip())
    return (None, content.strip())


def extract_markdown_from_statement(filepath: Path) -> str | None:
    """Extract just the markdown content from a statement file (excluding frontmatter).

    Returns None if the file doesn't exist or has no frontmatter block.
    """
    if not filepath.exists():
        return None
    frontmatter, body = split_frontmatter_body(filepath.read_text(encoding="utf-8"))
    return body if frontmatter is not None else None


def extract_frontmatter(filepath: Path) -> dict | None:
    """Parse the YAML frontmatter from a statement file.

    Returns None if the file doesn't exist or has no frontmatter block.
    """
    if not filepath.exists():
        return None
    frontmatter, _ = split_frontmatter_body(filepath.read_text(encoding="utf-8"))
    return frontmatter


def atomic_write_text(path: Path, text: str) -> None:
    """Write text via a same-directory temp file + rename.

    Every artifact this pipeline persists (statements, raw content, caches,
    generated JSON) is written through this, so a process killed mid-write (cron
    timeout, OOM, power loss) can never leave a truncated file. That matters
    because the exporter deliberately treats an unparseable statement as fatal —
    a torn write would otherwise break every subsequent nightly run.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Byte-content twin of atomic_write_text."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def clean_html_to_markdown(html_content: str, base_url: str) -> str:
    """Convert HTML content to clean markdown."""
    h = html2text.HTML2Text()
    h.body_width = 0
    h.baseurl = base_url
    markdown = h.handle(html_content)
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


# Date-stamp lines, in two flavours: an absolute date ("last reviewed 15 January
# 2025") or a relative counter ("Page last reviewed: 1 months ago"). The relative
# form ticks over on every scrape even when the statement text is unchanged, so it
# must be stripped here rather than surfacing as a spurious content diff. This
# whole-line form clears lines that are *only* a date stamp (standalone, or a
# metadata row with links).
_DATE_VALUE = (
    r"(?:\d{1,2}.*\d{4}|"
    r"\d+\s*(?:second|minute|hour|day|week|month|year)s?\s+ago|just now|yesterday|today)"
)
_LAST_REVIEWED_RE = re.compile(
    r"(?mi)^.*(?:last (?:reviewed|updated|modified)|date (?:published|modified)|page updated)"
    rf".*{_DATE_VALUE}.*$\n?",
)

# A date stamp that *trails* real prose on the same line, e.g. ACSQHC ended a
# content paragraph with "… implement AI technology. This statement was last
# updated on 20 February 2026." The whole-line form above would delete the real
# sentence too, so trim only the trailing stamp here, before it runs. Kept
# deliberately strict — a single clean sentence (no full stops, so no dotted
# URLs) following a full stop — so it never truncates a metadata/link row.
_INLINE_DATE_TAIL_RE = re.compile(
    r"(?im)(?<=[.])[ \t]+"
    r"[^.\n]*?(?:last (?:reviewed|updated|modified)|date (?:published|modified)|page updated)"
    r"[^.\n]*?"
    r"(?:\d{1,2}[^.\n]*?\d{4}|"
    r"\d+\s*(?:second|minute|hour|day|week|month|year)s?\s+ago|just now|yesterday|today)"
    r"[^.\n]*?\.?[ \t]*$"
)

# The mirror image: a stamp that *leads* the line, with real prose after it, e.g.
# DEWR's "This statement was last updated on 27 February 2026. It will be reviewed
# and updated annually…". Strip the leading stamp sentence (clean, full-stop
# terminated) and keep what follows.
_INLINE_DATE_HEAD_RE = re.compile(
    r"(?im)^[^.\n]*?(?:last (?:reviewed|updated|modified)|date (?:published|modified)|page updated)"
    r"[^.\n]*?"
    r"(?:\d{1,2}[^.\n]*?\d{4}|"
    r"\d+\s*(?:second|minute|hour|day|week|month|year)s?\s+ago|just now|yesterday|today)"
    r"[^.\n]*?\.[ \t]+"
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

# In-page navigation chrome that survives html2text as loose lines. None of it is
# statement content, and it either churns the diff or just clutters it. The
# leading `[ \t>*#-]*` (and optional `[`) lets each pattern reach the label
# through whatever heading/bullet/bold/quote markers html2text wrapped it in,
# while the `$` anchor keeps it from ever matching prose that merely contains the
# phrase (e.g. "The content on this page aligns with…").
#
# "On this page" table-of-contents label, plus the jump-link list it introduces
# when that list survives html2text (it is always a same-page anchor menu, never
# statement content). Where the list was already stripped upstream, only the
# orphan label remains and is removed on its own.
_ON_THIS_PAGE_RE = re.compile(
    r"(?mi)^[ \t>*#-]*on this page\**:?\**[ \t]*$\n"  # the label line
    r"(?:[ \t]*\n)*"  # blank lines
    r"(?:[ \t]*[*+-][ \t]+.*(?:\n|$))*"  # the jump-link list, if present
)
# "Back to top" / "Skip to content" affordances (the former repeated per section).
_BACK_TO_TOP_RE = re.compile(
    r"(?mi)^[ \t>*#-]*\[?[ \t]*(?:go )?back to top(?: of (?:the )?page)?"
    r"[ \t]*(?:\][ \t]*\([^)]*\))?[ \t]*$\n?"
)
_SKIP_LINK_RE = re.compile(
    r"(?mi)^[ \t>*#-]*\[?[ \t]*skip to [a-z][a-z ]*?"
    r"[ \t]*(?:\][ \t]*\([^)]*\))?[ \t]*$\n?"
)
# Headings emptied of their text (an icon or bare link stripped upstream).
_EMPTY_HEADING_RE = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]*$\n?")


# The date a page says it was last updated, read before the stamp is stripped
# from the body. Kept verbatim in frontmatter (`last_updated_text`) so the site
# can report the agency's own date without a model having to find it in prose.
_LAST_UPDATED_VALUE_RE = re.compile(
    r"(?i)last (?:reviewed|updated|modified)\b[^\n\d]{0,40}?"
    r"(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{4}|"
    r"\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})"
)


def extract_last_updated(text: str) -> str | None:
    """The page's own last-updated/reviewed date text, or None if it gives none."""
    match = _LAST_UPDATED_VALUE_RE.search(text)
    return match.group(1) if match else None


def clean_markdown(text: str) -> str:
    """Strip date stamps, classification markers, and navigation boilerplate."""
    # Trim inline stamps that share a line with prose (trailing, then leading),
    # keeping the prose, then clear any line that is wholly a date stamp.
    text = _INLINE_DATE_TAIL_RE.sub("", text)
    text = _INLINE_DATE_HEAD_RE.sub("", text)
    text = _LAST_REVIEWED_RE.sub("", text)
    text = _TRAILING_BOILERPLATE_RE.sub("", text)
    text = _OFFICIAL_MARKER_RE.sub("", text)
    text = _ALSO_INTERESTED_RE.sub("", text)
    text = _ON_THIS_PAGE_RE.sub("", text)
    text = _BACK_TO_TOP_RE.sub("", text)
    text = _SKIP_LINK_RE.sub("", text)
    text = _EMPTY_HEADING_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def format_markdown(text: str) -> str:
    """Apply deterministic markdown formatting to reduce diff variance."""
    return mdformat.text(text).strip()


def remove_boilerplate(element: Tag) -> None:
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
        # "Related content" / "you might also like" CTA card blocks (e.g. MoAD's
        # Drupal "loosely-related-auto" block). These rotate which tiles they show
        # on every render, so they churn the diff without being real edits.
        "[class*='loosely-related']",
        "[class*='related-content']",
        "[class*='related-links']",
        # In-page "jump to section" / "on this page" anchor menus. The desktop
        # copy usually sits in <nav>/<aside> (already stripped), but a duplicate
        # mobile menu (e.g. ACSQHC's "Go to section" toggle) often sits loose in
        # the content and leaks its heading as nav chrome.
        "[class*='anchor-nav']",
        "[class*='anchor-toggle']",
        # Carousels / sliders are decorative nav-card strips in these statements,
        # never the transparency text itself. They rotate their tiles per render,
        # so strip them directly — not only when wrapped in a "related" block (as
        # MoAD's happen to be). Covers slick, swiper and generic carousel markup.
        "[class*='carousel']",
        "[class*='slick']",
        "[class*='swiper']",
    ]

    for selector in boilerplate_selectors:
        for tag in element.select(selector):
            tag.decompose()

    # Remove email protection links (hashes change on every visit)
    # Replace with just the link text
    for link in element.find_all("a", href=re.compile(r"cdn-cgi/l/email-protection")):
        link.replace_with(link.get_text())


# SharePoint "page schema" pages (Home Affairs) ship the statement body as JSON
# in a hidden form field and render its tabs client-side, so the served HTML
# holds only the introduction. The field's value is {"content": [{"text":
# <heading>, "block": <html>}, …]}; inline those blocks as sections so the
# statement is captured whole.
_PAGE_SCHEMA_FIELD_SUFFIX = "PageSchemaHiddenField$Input"


def inline_page_schema(soup: BeautifulSoup) -> int:
    """Append hidden page-schema content blocks to the page's main element.

    Returns the number of blocks inlined (0 when the page has no such field).
    """
    fields = [
        el
        for el in soup.find_all("input", attrs={"type": "hidden"})
        if str(el.get("name", "")).endswith(_PAGE_SCHEMA_FIELD_SUFFIX)
    ]
    if not fields:
        return 0
    host = soup.find("main") or soup.find("body") or soup
    count = 0
    for field in fields:
        try:
            data = json.loads(str(field.get("value", "")))
        except json.JSONDecodeError:
            continue
        for item in data.get("content", []) if isinstance(data, dict) else []:
            block = item.get("block") if isinstance(item, dict) else None
            if not block:
                continue
            section = soup.new_tag("section")
            if heading := item.get("text"):
                h2 = soup.new_tag("h2")
                h2.string = str(heading)
                section.append(h2)
            section.append(BeautifulSoup(str(block), "lxml"))
            host.append(section)
            count += 1
    return count


def extract_main_content(soup: BeautifulSoup, selector: str | None = None) -> str:
    """Extract the main content from the page, removing navigation and footers.

    Args:
        soup: BeautifulSoup object of the page
        selector: Optional CSS selector to use instead of default list
    """
    inline_page_schema(soup)
    if selector:
        if main_content := soup.select_one(selector):
            remove_boilerplate(main_content)
            return str(main_content)
    else:
        for candidate in ["main", "article", ".content", "#content", ".main-content"]:
            if main_content := soup.select_one(candidate):
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
            # logger.exception: an unexpected error here may be a programming
            # bug, so keep the traceback rather than a one-line summary.
            logger.exception(f"Error fetching {agency.name}")
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

    # Trust the Content-Type header, but fall back to the file magic: some
    # servers label PDFs application/octet-stream.
    is_pdf = "application/pdf" in (data["content_type"] or "") or data[
        "content"
    ].startswith(b"%PDF-")
    extension = "pdf" if is_pdf else "html"
    filepath = raw_dir / f"{agency.abbr}.{extension}"
    stale = raw_dir / f"{agency.abbr}.{'html' if is_pdf else 'pdf'}"
    stale.unlink(missing_ok=True)

    atomic_write_bytes(filepath, data["content"])

    meta = {"final_url": data["final_url"], "content_type": data["content_type"]}
    atomic_write_text(raw_dir / f"{agency.abbr}.meta.json", json.dumps(meta))

    logger.info(f"Saved raw content to {agency.abbr}.{extension}")
    return True


def _load_final_url(agency: Agency, raw_dir: Path) -> str | None:
    """Final URL recorded at fetch time, falling back to the agency's URL.

    meta.json also records the response content_type, but that is debugging
    breadcrumb only — nothing downstream consumes it.
    """
    meta_path = raw_dir / f"{agency.abbr}.meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return meta.get("final_url") or agency.url
    return agency.url


def process_raw(agency: Agency, raw_dir: Path) -> StatementResult:
    """Process raw content from file into markdown."""
    logger.info(f"Processing raw content for {agency.name}...")

    final_url = _load_final_url(agency, raw_dir)

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
                "last_updated": extract_last_updated(raw_text),
            }
        except Exception as e:
            logger.exception(f"Error processing PDF for {agency.name}")
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
            raw_markdown = clean_html_to_markdown(
                extract_main_content(soup, agency.selector), agency.url or ""
            )
            markdown = clean_markdown(raw_markdown)

            return {
                "title": title,
                "markdown": markdown or None,
                "status_code": 200,
                "final_url": final_url,
                "error": None,
                "source_type": "html",
                "last_updated": extract_last_updated(raw_markdown),
            }
        except Exception as e:
            logger.exception(f"Error processing HTML for {agency.name}")
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


def save_statement(
    agency: Agency, data: StatementResult, output_dir: Path
) -> SaveStatus:
    """Save statement as markdown file with YAML frontmatter.

    For HTML sources, applies markdown cleanup + mdformat and writes the result.
    For PDF sources, applies the deterministic `clean_markdown` pass (date stamps,
    OFFICIAL markers, nav chrome) but not mdformat — PDF extraction is too ragged
    to reflow safely, so richer cleanup is left to the scrape skill in a separate
    step. The `raw_hash` field keys on the *raw* extracted text, so PDF-change
    detection is unaffected: if the raw text is unchanged from the last save
    (matching `raw_hash`), the write is skipped entirely so skill-cleaned bodies
    aren't clobbered.

    Returns "warned" (file still written) when the new content shrank past
    CONTENT_SHRINKAGE_THRESHOLD, so callers can surface it in the exit code.
    """
    if data["error"] or not data["markdown"]:
        logger.warning(f"Skipping {agency.abbr} due to fetch error")
        return "failed"

    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"{agency.abbr}.md"
    is_pdf = data["source_type"] == "pdf"

    if is_pdf:
        # Hash the raw extracted text (not the cleaned body) so change detection
        # stays keyed on the PDF itself; clean the body only if we don't skip.
        new_raw_hash = hashlib.sha256(data["markdown"].encode("utf-8")).hexdigest()
        existing = extract_frontmatter(filepath) or {}
        if existing.get("raw_hash") == new_raw_hash:
            logger.info(f"Skipping {agency.abbr}: PDF unchanged (raw_hash match)")
            return "saved"
        new_body = clean_markdown(data["markdown"])
    else:
        new_body = format_markdown(data["markdown"])
        new_raw_hash = None

    shrunk = False
    existing_markdown = extract_markdown_from_statement(filepath)
    if existing_markdown is not None and not is_pdf:
        old_len = len(existing_markdown)
        new_len = len(new_body)
        if old_len > 0 and new_len < old_len * CONTENT_SHRINKAGE_THRESHOLD:
            shrunk = True
            shrinkage_pct = (1 - new_len / old_len) * 100
            logger.warning(
                f"CONTENT SHRINKAGE DETECTED for {agency.abbr}: "
                f"content reduced by {shrinkage_pct:.0f}% "
                f"({old_len} -> {new_len} chars). "
                f"This may indicate a scraping failure."
            )

    # Log-only, never in the exit code: terseness is a persistent property of a
    # statement, so gating on it would fail every nightly run for that agency.
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
    if last_updated := data.get("last_updated"):
        frontmatter["last_updated_text"] = last_updated
    if is_pdf:
        frontmatter["raw_hash"] = new_raw_hash

    yaml_str = yaml.dump(
        frontmatter, default_flow_style=False, allow_unicode=True
    ).strip()
    content = f"---\n{yaml_str}\n---\n\n{new_body}"

    atomic_write_text(filepath, content)
    logger.info(f"Saved {agency.abbr}.md")
    return "warned" if shrunk else "saved"


def process_statements(
    agencies: list[Agency], raw_dir: Path, output_dir: Path
) -> ProcessCounts:
    """Process each agency's raw file into a statement, isolating failures.

    One agency's unexpected exception (an mdformat edge case, malformed
    frontmatter) is logged and counted as a failure rather than aborting the
    remaining batch — the same per-agency isolation every other stage has.
    """
    saved = warned = failed = 0
    for agency in agencies:
        try:
            status = save_statement(agency, process_raw(agency, raw_dir), output_dir)
        except Exception:
            logger.exception(f"Unexpected error processing {agency.abbr}")
            status = "failed"
        if status == "saved":
            saved += 1
        elif status == "warned":
            warned += 1
        else:
            failed += 1
    return ProcessCounts(saved=saved, warned=warned, failed=failed)


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
