"""Export the statement corpus + git history as JSON for the static site.

Reads `agencies.toml`, the `statements/*.md` corpus, and the git history, and
writes a set of JSON artifacts under `site/src/generated/` (plus a slim
`site/public/data/` file for the client-fetched similarity graph) that the Astro
site consumes at build time.

The artifacts are fully derivable from the repo, so they are gitignored and
regenerated in CI; only the embeddings cache (`.cache/embeddings.json`) is
committed. All JSON is written deterministically (sorted keys, rounded floats)
so CI output is byte-reproducible and diffs stay clean.

This module asserts text *co-occurrence* between statements; it never claims a
directional "agency A copied from B". The most it says is that a passage also
appears in the DTA template (`alsoInDta`), which is defensible because the DTA
publishes the canonical policy.
"""

import hashlib
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .scraper import (
    extract_frontmatter,
    extract_markdown_from_statement,
    logger,
)

# Agencies with an empty `url` in agencies.toml that are within the AI Policy's
# mandate but simply have not published yet (highest likelihood of a future
# statement). Every other empty-url agency is treated as exempt / out-of-scope
# (intelligence & defence portfolio, or corporate Commonwealth entities). See the
# empty-url-agencies-triage note for the full reasoning.
NOT_YET_ABBRS = frozenset({"AIATSIS", "APVMA"})

REPO_ROOT = Path.cwd()
STATEMENTS_DIR = REPO_ROOT / "statements"
AGENCIES_TOML = REPO_ROOT / "agencies.toml"
GENERATED_DIR = REPO_ROOT / "site" / "src" / "generated"
PUBLIC_DATA_DIR = REPO_ROOT / "site" / "public" / "data"


# --- small shared helpers ---------------------------------------------------


def git(*args: str) -> str:
    """Run a git command at the repo root and return stdout with newlines trimmed.

    Only newlines are trimmed (not str.strip()): Python treats the ASCII field/
    record separators \\x1e/\\x1d used in our `git log` format as whitespace, so a
    bare .strip() would eat the trailing separators off the last record.
    """
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    return result.stdout.strip("\n")


def split_frontmatter_body(content: str) -> tuple[dict, str]:
    """Split a statement file's text into (frontmatter dict, markdown body).

    Mirrors the `---\\n` splitting used by scraper.extract_frontmatter and
    scraper.extract_markdown_from_statement, but operates on a string so it can
    be reused for `git show` output (which never touches the filesystem).

    Historical revisions occasionally carry non-safe frontmatter (e.g. a PDF
    title serialised as a pypdf object tag); since callers walking history only
    need the body, an unparseable frontmatter degrades to {} rather than failing.
    """
    parts = content.split("---\n", 2)
    if len(parts) >= 3:
        try:
            frontmatter = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            frontmatter = {}
        return (frontmatter, parts[2].strip())
    return ({}, content.strip())


def write_json(path: Path, obj: object) -> None:
    """Write `obj` as deterministic, human-diffable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# --- loading ----------------------------------------------------------------


def load_agency_records() -> list[dict]:
    """Load all agency rows from agencies.toml, preserving `size`.

    scraper.load_agencies() drops the `size` field, which the coverage view
    needs, so the exporter reads the toml directly.
    """
    with open(AGENCIES_TOML, "rb") as f:
        data = tomllib.load(f)
    return [
        {
            "name": d["name"],
            "abbr": d["abbr"],
            "url": d["url"] or None,
            "size": d.get("size", "unknown"),
            "manual": d.get("manual", False),
        }
        for d in data["agencies"]
    ]


def statement_status(abbr: str, url: str | None, has_statement: bool) -> str:
    """Classify an agency as published / not-yet / exempt."""
    if has_statement:
        return "published"
    if abbr in NOT_YET_ABBRS:
        return "not-yet"
    if url is None:
        return "exempt"
    return "not-yet"


def source_type(frontmatter: dict) -> str:
    """PDF-sourced statements carry a `raw_hash`; everything else is HTML."""
    return "pdf" if "raw_hash" in frontmatter else "html"


# --- git timeline + de-noising ----------------------------------------------

# ASCII field/record separators frame the `git log` output robustly: commit
# subjects and bodies are multi-line, so ordinary delimiters would be ambiguous.
_FS = "\x1e"
_RS = "\x1d"

# Bulk migration commits touch many statement files at once (e.g. the initial
# import). A statement first seen in such a commit was not "published" that day;
# the site labels it "tracked since" instead.
_BULK_IMPORT_THRESHOLD = 20

# Commit messages self-annotate spurious scrape churn (nav chrome, formatting
# regressions). Surviving events matching these are flagged so the timeline feed
# can hide them by default.
_NOISE_RE = re.compile(
    r"(?i)spurious|nav-tile|nav-card|related-pages|download-widget|"
    r"cleanup-pipeline|leaked into the diff|go to section"
)

_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Revision:
    """One commit in a statement file's history, with its body at that revision."""

    sha: str
    date: str  # author date, ISO-8601 with offset
    subject: str  # commit subject (first line)
    message: str  # commit body (the explanatory bullets)
    body: str  # statement markdown at this revision
    body_key: str  # hash of the whitespace-collapsed body (revert-collapse key)
    bulk: bool  # introduced by a bulk-import commit


def _body_key(body: str) -> str:
    """Hash a body ignoring whitespace, so pure mdformat re-wraps compare equal."""
    return hashlib.sha256(_WS_RE.sub(" ", body).strip().encode("utf-8")).hexdigest()


def bulk_import_shas() -> frozenset[str]:
    """SHAs of commits that touch more than _BULK_IMPORT_THRESHOLD statement files."""
    raw = git("log", "--format=%H", "--name-only", "--", "statements")
    counts: dict[str, int] = {}
    current = ""
    for line in raw.splitlines():
        if re.fullmatch(r"[0-9a-f]{40}", line):
            current = line
        elif line.startswith("statements/"):
            counts[current] = counts.get(current, 0) + 1
    return frozenset(sha for sha, n in counts.items() if n > _BULK_IMPORT_THRESHOLD)


def git_file_revisions(abbr: str, bulk: frozenset[str]) -> list[Revision]:
    """Chronological revisions of statements/<abbr>.md, body included per revision."""
    rel = f"statements/{abbr}.md"
    raw = git(
        "log",
        "--follow",
        "--date-order",
        f"--format=%H{_FS}%aI{_FS}%s{_FS}%b{_RS}",
        "--",
        rel,
    )
    revisions: list[Revision] = []
    for record in raw.split(_RS):
        record = record.strip("\n")
        if not record:
            continue
        sha, date, subject, message = record.split(_FS)
        _, body = split_frontmatter_body(git("show", f"{sha}:{rel}"))
        revisions.append(
            Revision(
                sha=sha,
                date=date,
                subject=subject,
                message=message.strip(),
                body=body,
                body_key=_body_key(body),
                bulk=sha in bulk,
            )
        )
    revisions.reverse()  # oldest first
    return revisions


def collapse_reverts(revisions: list[Revision]) -> list[Revision]:
    """Drop no-net-change excursions (spurious commit + its revert) and formatting churn.

    Walks chronologically tracking body content. A revision whose body matches the
    current tip adds nothing (pure metadata/formatting churn) and is dropped. A
    revision whose body matches an *earlier* state means the corpus excursed and
    returned (e.g. MOADOPH's nav-tile commit then its revert), so we roll back to
    that earlier state — both the excursion and its undo vanish.
    """
    kept: list[Revision] = []
    for rev in revisions:
        if kept and rev.body_key == kept[-1].body_key:
            continue
        match = next(
            (
                i
                for i in range(len(kept) - 1, -1, -1)
                if kept[i].body_key == rev.body_key
            ),
            None,
        )
        if match is not None:
            del kept[match + 1 :]
            continue
        kept.append(rev)
    return kept


def _is_noise(rev: Revision) -> bool:
    return bool(_NOISE_RE.search(rev.subject) or _NOISE_RE.search(rev.message))


def _event_kind(index: int, rev: Revision) -> str:
    """First-seen events: 'tracked-since' if bulk-imported, else 'published'.

    A statement first seen in a bulk-migration commit has no real publication date,
    so it is "tracked since" rather than "published". Every later change is an
    'updated' event (even if it rode in on a mass re-scrape — that is still real
    content change, so it is NOT marked tracked-since).
    """
    if index == 0:
        return "tracked-since" if rev.bulk else "published"
    return "updated"


def timeline_entries(revisions: list[Revision]) -> list[dict]:
    """Per-statement timeline rows (full body included for build-time diffing)."""
    entries: list[dict] = []
    prev_chars = 0
    for i, rev in enumerate(revisions):
        chars = len(rev.body)
        entries.append(
            {
                "sha": rev.sha,
                "date": rev.date,
                "subject": rev.subject,
                "message": rev.message,
                "kind": _event_kind(i, rev),
                "isNoise": _is_noise(rev),
                "chars": chars,
                "charDelta": chars - prev_chars,
                "body": rev.body,
            }
        )
        prev_chars = chars
    return entries


# --- artifact builders ------------------------------------------------------


def build_statement_doc(
    abbr: str, frontmatter: dict, body: str, timeline: list[dict]
) -> dict:
    """Per-statement document (originality/neighbours/passages added later)."""
    doc: dict = {
        "abbr": abbr,
        "agency": frontmatter.get("agency", abbr),
        "title": frontmatter.get("title", f"{abbr} AI transparency statement"),
        "sourceUrl": frontmatter.get("source_url"),
        "sourceType": source_type(frontmatter),
        "body": body,
        "frontmatter": frontmatter,
        "timeline": timeline,
    }
    if frontmatter.get("final_url"):
        doc["finalUrl"] = frontmatter["final_url"]
    return doc


def build_agency_index(
    records: list[dict],
    statements: dict[str, dict],
    timelines: dict[str, list[Revision]],
) -> list[dict]:
    """Index of every agency with coverage status + revision summary, sorted by abbr."""
    index = []
    for rec in records:
        abbr = rec["abbr"]
        has_statement = abbr in statements
        revs = timelines.get(abbr, [])
        index.append(
            {
                "abbr": abbr,
                "name": rec["name"],
                "size": rec["size"],
                "url": rec["url"],
                "status": statement_status(abbr, rec["url"], has_statement),
                "statementId": abbr if has_statement else None,
                "firstSeen": revs[0].date if revs else None,
                "firstSeenIsBulkImport": revs[0].bulk if revs else None,
                "lastUpdated": revs[-1].date if revs else None,
                "revisionCount": len(revs),
            }
        )
    return sorted(index, key=lambda a: a["abbr"])


def build_timeline(
    timelines: dict[str, list[Revision]],
    records: list[dict],
    statements: dict[str, dict],
) -> list[dict]:
    """Flat, reverse-chronological feed of every change event (no bodies)."""
    sizes = {r["abbr"]: r["size"] for r in records}
    events = []
    for abbr, revs in timelines.items():
        agency = statements[abbr]["frontmatter"].get("agency", abbr)
        for i, rev in enumerate(revs):
            events.append(
                {
                    "id": f"{abbr}:{rev.sha[:10]}",
                    "sha": rev.sha,
                    "date": rev.date,
                    "statementId": abbr,
                    "abbr": abbr,
                    "agency": agency,
                    "size": sizes.get(abbr, "unknown"),
                    "summary": rev.subject,
                    "kind": _event_kind(i, rev),
                    "isNoise": _is_noise(rev),
                }
            )
    return sorted(events, key=lambda e: (e["date"], e["id"]), reverse=True)


def load_statements() -> dict[str, dict]:
    """Read every statements/*.md into {abbr: {frontmatter, body}}."""
    statements: dict[str, dict] = {}
    for path in sorted(STATEMENTS_DIR.glob("*.md")):
        abbr = path.stem
        frontmatter = extract_frontmatter(path)
        body = extract_markdown_from_statement(path)
        if frontmatter is None or body is None:
            logger.warning("Could not parse %s; skipping", path.name)
            continue
        statements[abbr] = {"frontmatter": frontmatter, "body": body}
    return statements


def main() -> int:
    """Generate the JSON artifacts the static site consumes."""
    if not STATEMENTS_DIR.exists():
        logger.error("Error: %s directory not found", STATEMENTS_DIR)
        return 1

    logger.info("Starting export at %s", datetime.now(UTC).isoformat())

    records = load_agency_records()
    statements = load_statements()
    logger.info("Loaded %d agencies, %d statements", len(records), len(statements))

    logger.info("Walking git history for %d statements...", len(statements))
    bulk = bulk_import_shas()
    timelines = {
        abbr: collapse_reverts(git_file_revisions(abbr, bulk)) for abbr in statements
    }
    total_revisions = sum(len(r) for r in timelines.values())

    agency_index = build_agency_index(records, statements, timelines)
    statuses = [a["status"] for a in agency_index]
    timeline = build_timeline(timelines, records, statements)

    statement_docs = {
        abbr: build_statement_doc(
            abbr, data["frontmatter"], data["body"], timeline_entries(timelines[abbr])
        )
        for abbr, data in statements.items()
    }

    first_commit = git("log", "--reverse", "--format=%aI", "--max-parents=0")
    meta = {
        "headSha": git("rev-parse", "HEAD"),
        "builtAt": datetime.now(UTC).isoformat(),
        "firstCommit": first_commit.splitlines()[0] if first_commit else None,
        "counts": {
            "agencies": len(records),
            "published": statuses.count("published"),
            "notYet": statuses.count("not-yet"),
            "exempt": statuses.count("exempt"),
            "statements": len(statements),
            "revisions": total_revisions,
        },
    }

    write_json(GENERATED_DIR / "agencies.json", {"agencies": agency_index})
    write_json(GENERATED_DIR / "timeline.json", {"events": timeline})
    for abbr, doc in statement_docs.items():
        write_json(GENERATED_DIR / "statements" / f"{abbr}.json", doc)
    write_json(GENERATED_DIR / "meta.json", meta)

    logger.info(
        "Exported: %d agencies (%d published, %d not-yet, %d exempt), "
        "%d statements, %d timeline events",
        meta["counts"]["agencies"],
        meta["counts"]["published"],
        meta["counts"]["notYet"],
        meta["counts"]["exempt"],
        meta["counts"]["statements"],
        len(timeline),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
