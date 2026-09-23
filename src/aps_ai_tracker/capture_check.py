"""Check that each capture is the agency's statement at all.

The scraper saves whatever the tracked URL returns. Usually that is the
statement, but sometimes it is a WAF block page served with a 200, an index or
hub page that only links to the statement, a capture that failed part-way, or
a different document at a reused URL. None of these is the agency changing
its statement, and every later reading built on one is wrong. Claude reads
each distinct capture once and says which it is; the exporter drops captures
judged not to be the statement, exactly as it drops a `captures.toml`
quarantine, unless the operator has confirmed the capture genuine.

Results are cached by (agency, body) hash in `.cache/captures.json`. Without a
backend an unchecked capture is let through, like an unclassified change.
"""

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from . import llm
from .scraper import logger

SCHEMA_VERSION = 1
CACHE_PATH = llm.CACHE_DIR / "captures.json"

Verdict = Literal[
    "statement",
    "block-page",
    "index-or-hub",
    "partial",
    "other-document",
]


class CaptureAssessment(BaseModel):
    """Claude's verdict on one capture."""

    verdict: Verdict
    reason: str = Field(description="One plain sentence saying what the page is")
    statement_link: str | None = Field(
        description=(
            "For an index-or-hub page: the URL of the link on the page that "
            "appears to lead to the statement, copied exactly. Otherwise null."
        )
    )


@dataclass(frozen=True, slots=True)
class CaptureCheck:
    verdict: str
    reason: str
    statement_link: str | None = None

    @property
    def is_statement(self) -> bool:
        return self.verdict == "statement"


SYSTEM_PROMPT = """\
Australian Government agencies publish AI transparency statements under the
Policy for the responsible use of AI in government. A tracker fetches each
agency's statement from a fixed URL and converts the page or PDF to Markdown.
You are shown one such capture. Decide whether it is the agency's AI
transparency statement.

Verdicts:
- statement: the agency's AI transparency statement, or a page whose main
  content is that statement. A short statement counts, including one that says
  the agency relies on another body and refers to that body's statement. Page
  chrome around the statement (navigation, footers, related links) is fine.
- block-page: a web application firewall or bot-challenge page ("Access
  Denied", "Just a moment...", "verifying you are human", an incident ID).
- index-or-hub: a page that lists or links to the statement (or to many
  documents, such as an accountability and reporting page) without containing
  the statement's content itself.
- partial: the capture is plainly the statement page but most of its content
  is missing: only a title, a banner image, an introduction that stops, or
  frontmatter with no body.
- other-document: some other document entirely (a corporate plan, a general AI
  policy or principles page that is not framed as the transparency statement,
  an unrelated page).

Judge the capture by what it contains, not by how well it meets the Standard: a
thin or non-compliant statement is still a statement. When unsure between
statement and anything else, choose statement. For index-or-hub, copy the most
likely statement link into `statement_link`.
"""


def _key(agency: str, body: str) -> str:
    return hashlib.sha256(f"{agency}\n{body}".encode()).hexdigest()[:24]


def _user_prompt(agency: str, body: str) -> str:
    return f"Agency: {agency}\n\nCapture (Markdown):\n\n{body}"


def _from_cache(entry: dict) -> CaptureCheck:
    return CaptureCheck(entry["verdict"], entry["reason"], entry.get("statement_link"))


def check_captures(captures: dict[str, tuple[str, str]]) -> dict[str, CaptureCheck]:
    """Verdicts for {id: (agency, body)}; ids with no verdict were not checked.

    An id is missing from the result only when the capture is uncached and no
    backend is available (or its call failed); callers let those through.
    """
    cache = llm.load_cache(CACHE_PATH)
    on_disk = dict(cache)
    results: dict[str, CaptureCheck] = {}
    jobs: dict[str, tuple[str, str, type[CaptureAssessment]]] = {}
    job_ids: dict[str, list[str]] = {}

    for cid, (agency, body) in captures.items():
        key = _key(agency, body)
        entry = cache.get(key)
        if entry and entry.get("v") == SCHEMA_VERSION:
            results[cid] = _from_cache(entry)
            continue
        jobs[key] = (SYSTEM_PROMPT, _user_prompt(agency, body), CaptureAssessment)
        job_ids.setdefault(key, []).append(cid)

    if jobs and not llm.api_available():
        logger.warning("No Claude backend available; %d captures unchecked", len(jobs))
    elif jobs:
        logger.info("Checking %d captures via %s...", len(jobs), llm.MODEL)
        for key, a in llm.extract_many(jobs).items():
            cache[key] = {
                "v": SCHEMA_VERSION,
                "model": llm.MODEL,
                "verdict": a.verdict,
                "reason": a.reason.strip(),
                "statement_link": a.statement_link,
            }
            for cid in job_ids[key]:
                results[cid] = _from_cache(cache[key])

    live = {_key(agency, body) for agency, body in captures.values()}
    pruned = {
        k: v for k, v in cache.items() if k in live and v.get("v") == SCHEMA_VERSION
    }
    if pruned != on_disk:
        llm.save_cache(CACHE_PATH, pruned)
    return results
