"""Classify what each revision of a statement actually changed.

The scraper's git history records every time a statement file changed, but
"changed" spans everything from a rotating sidebar leaking through the cleaner
to an agency rewriting its statement from scratch. This module reads the diff
content itself (not the commit message) and assigns each revision pair one of a
fixed set of change kinds:

- noise (`formatting`, `link-churn`, `chrome`, `date-stamp`, `scrape-noise`):
  nothing the agency wrote changed
- cosmetic (`reordering`, `cosmetic`): wording or layout tweaks with no change
  of substance
- content (`expansion`, `restructure`, `substantive`): the statement's substance
  changed; `substantive` means a claim or commitment was added, removed or
  altered

Cheap deterministic rules catch the mechanical cases; everything else goes to
Claude with the diff, which also writes a one-sentence plain-English summary and
lists the noteworthy additions and removals. Results are cached by body hash so
history is classified once.
"""

import difflib
import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from . import llm
from .scraper import logger

SCHEMA_VERSION = 1
CACHE_PATH = llm.CACHE_DIR / "changes.json"

NOISE_KINDS = frozenset(
    {"formatting", "link-churn", "chrome", "date-stamp", "scrape-noise"}
)
COSMETIC_KINDS = frozenset({"reordering", "cosmetic"})
CONTENT_KINDS = frozenset({"expansion", "restructure", "substantive"})
UNCLASSIFIED = "unclassified"

_WS_RE = re.compile(r"\s+")
_MD_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_LINK_TARGET_RE = re.compile(r"\]\(([^)]*)\)")
# A changed line that is wholly page chrome: an image, a bare link, or a heading
# whose only text is a link (the "you may also be interested in" tile pattern).
_CHROME_LINE_RE = re.compile(
    r"^\s*(?:[-*+]\s+|#{1,6}\s+)?!?\[[^\]]*\]\([^)]*\)\s*$|^\s*!\[[^\]]*\]\([^)]*\)\s*$"
)
_DATE_STAMP_RE = re.compile(
    r"(?i)(?:last (?:reviewed|updated|modified)|date (?:published|modified)|"
    r"page updated|reviewed on|updated on)"
    r".*(?:\d{4}|\d+\s*(?:second|minute|hour|day|week|month|year)s?\s+ago|"
    r"just now|yesterday|today)"
)


class ChangeAssessment(BaseModel):
    """Claude's reading of one revision diff."""

    kind: Literal["scrape-noise", "cosmetic", "expansion", "restructure", "substantive"]
    summary: str = Field(
        description="One plain-English sentence (max 30 words) for a policy reader"
    )
    noteworthy: list[str] = Field(
        description=(
            "Specific additions, removals or alterations of substance, most "
            "important first; removals prefixed 'Removed:'. Empty unless kind is "
            "substantive or restructure."
        )
    )


@dataclass(frozen=True, slots=True)
class Classification:
    kind: str
    method: str  # rule | llm | uncached
    summary: str | None = None
    noteworthy: list[str] = field(default_factory=list)

    @property
    def is_noise(self) -> bool:
        return self.kind in NOISE_KINDS

    @property
    def is_content(self) -> bool:
        return self.kind in CONTENT_KINDS


# --- deterministic rules ----------------------------------------------------


def _text_only(body: str) -> str:
    """Body reduced to its words: no links, markup, punctuation, case or spacing."""
    t = _MD_LINK_RE.sub(r"\1", body)
    t = re.sub(r"[*_`~#>|\\-]", " ", t)
    t = re.sub(r"[^\w\s]", " ", t.lower())
    return _WS_RE.sub(" ", t).strip()


def _link_targets(body: str) -> list[str]:
    return _LINK_TARGET_RE.findall(body)


def _passage_multiset(body: str) -> list[str]:
    return sorted(
        _text_only(block) for block in re.split(r"\n\s*\n", body) if block.strip()
    )


def changed_lines(prev: str, cur: str) -> list[str]:
    """Non-blank lines that differ between two bodies (both sides, markers stripped)."""
    out = []
    for line in difflib.unified_diff(
        prev.splitlines(), cur.splitlines(), lineterm="", n=0
    ):
        if line.startswith(("---", "+++", "@@")):
            continue
        if line[1:].strip():
            out.append(line[1:].strip())
    return out


def rule_kind(prev: str, cur: str) -> str | None:
    """Mechanical classification, or None when the diff needs reading."""
    if _text_only(prev) == _text_only(cur):
        return (
            "link-churn" if _link_targets(prev) != _link_targets(cur) else "formatting"
        )
    lines = changed_lines(prev, cur)
    if lines and all(_CHROME_LINE_RE.match(line) for line in lines):
        return "chrome"
    if lines and all(_DATE_STAMP_RE.search(line) for line in lines):
        return "date-stamp"
    if _passage_multiset(prev) == _passage_multiset(cur):
        return "reordering"
    return None


# --- Claude classification --------------------------------------------------

SYSTEM_PROMPT = """\
You classify revisions of Australian Government AI transparency statements.

Every Commonwealth agency must publish a statement describing how it uses AI,
under the Digital Transformation Agency's Policy for the responsible use of AI in
government. A tracker scrapes each statement daily and records every change to
the file. You are shown the unified diff between two consecutive captures of one
agency's statement (Markdown converted from the agency's web page or PDF). Decide
what kind of change it is and describe it for an educated policy reader.

Kinds:
- scrape-noise: nothing the agency wrote changed. The diff is page chrome leaking
  through the scraper (navigation tiles, "you may also be interested in"
  sidebars, cookie banners, share widgets), a relative date stamp ticking over
  ("2 days ago" to "6 days ago"), a truncated or failed capture, or a different
  page layout of the same text.
- cosmetic: the agency edited the page, but only wording, punctuation, typos,
  formatting, link targets, or a "last updated" date. No change of substance.
- expansion: the substance is the same but is now said at more length or in
  more detail (a bullet point grown into a paragraph, an example added to an
  existing claim). Nothing new is claimed or promised and nothing is dropped.
- restructure: sections reorganised, merged, split or reworded so that the
  document reads differently, but the claims and commitments are substantially
  the same.
- substantive: a claim, commitment, fact or disclosure was added, removed or
  altered. Examples: a new use of AI disclosed; an officer appointed; a
  commitment such as "we will not use AI where the public may directly interact
  with it without a human" added or removed; a tool named or dropped; the review
  cadence changed; a contact point changed; a whole rewrite.

Removals matter more than additions. A dropped commitment, safeguard, or
disclosure is always substantive and always belongs in `noteworthy`, prefixed
"Removed:". An expansion that keeps the same substance is never substantive.

Write `summary` as one sentence of at most 30 words, in plain Australian
English, naming the agency's action ("Names a Chief AI Officer and drops its
commitment to keep AI away from public-facing decisions."). No preamble, no
hedging, no "the diff shows". Use `noteworthy` for the specific substantive
points, one short phrase each, most important first.
"""


def _pair_key(prev: str, cur: str) -> str:
    def h(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    return f"{h(prev)}:{h(cur)}"


def _diff_text(prev: str, cur: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            prev.splitlines(),
            cur.splitlines(),
            fromfile="previous",
            tofile="current",
            lineterm="",
            n=3,
        )
    )


def _user_prompt(agency: str, prev: str, cur: str) -> str:
    return (
        f"Agency: {agency}\n\nUnified diff between the previous and current "
        f"capture of its AI transparency statement:\n\n{_diff_text(prev, cur)}"
    )


def _from_cache(entry: dict) -> Classification:
    return Classification(
        kind=entry["kind"],
        method="llm",
        summary=entry["summary"],
        noteworthy=list(entry["noteworthy"]),
    )


def classify_pairs(
    pairs: dict[str, tuple[str, str, str]],
) -> dict[str, Classification]:
    """Classify {id: (agency, prev_body, cur_body)}; cached, rule-first.

    Pairs the rules can't settle and the cache doesn't hold are sent to Claude
    when a key is present; otherwise they come back `unclassified` so the caller
    can fall back to its older heuristics.
    """
    cache = llm.load_cache(CACHE_PATH)
    on_disk = dict(cache)
    results: dict[str, Classification] = {}
    jobs: dict[str, tuple[str, str, type[ChangeAssessment]]] = {}
    job_ids: dict[str, list[str]] = {}

    for pair_id, (agency, prev, cur) in pairs.items():
        kind = rule_kind(prev, cur)
        if kind is not None:
            results[pair_id] = Classification(kind=kind, method="rule")
            continue
        key = _pair_key(prev, cur)
        entry = cache.get(key)
        if entry and entry.get("v") == SCHEMA_VERSION:
            results[pair_id] = _from_cache(entry)
            continue
        jobs[key] = (SYSTEM_PROMPT, _user_prompt(agency, prev, cur), ChangeAssessment)
        job_ids.setdefault(key, []).append(pair_id)

    if jobs and not llm.api_available():
        logger.warning(
            "ANTHROPIC_API_KEY absent; %d revision pairs left unclassified", len(jobs)
        )
    elif jobs:
        logger.info("Classifying %d revision pairs via %s...", len(jobs), llm.MODEL)
        for key, assessment in llm.extract_many(jobs).items():
            cache[key] = {
                "v": SCHEMA_VERSION,
                "model": llm.MODEL,
                "kind": assessment.kind,
                "summary": assessment.summary.strip(),
                "noteworthy": [n.strip() for n in assessment.noteworthy if n.strip()],
            }
            for pair_id in job_ids[key]:
                results[pair_id] = _from_cache(cache[key])

    for key, ids in job_ids.items():
        for pair_id in ids:
            results.setdefault(
                pair_id, Classification(kind=UNCLASSIFIED, method="uncached")
            )

    # Prune entries for pairs no longer in any timeline (superseded by a
    # revert-collapse or schema bump) so the committed cache tracks the corpus.
    live = {_pair_key(p, c) for _, p, c in pairs.values()}
    pruned = {
        k: v for k, v in cache.items() if k in live and v.get("v") == SCHEMA_VERSION
    }
    if pruned != on_disk:
        llm.save_cache(CACHE_PATH, pruned)
    return results
