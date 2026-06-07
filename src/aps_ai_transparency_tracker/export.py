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

import json
import subprocess
import sys
import tomllib
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
    """Run a git command at the repo root and return stripped stdout."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def split_frontmatter_body(content: str) -> tuple[dict, str]:
    """Split a statement file's text into (frontmatter dict, markdown body).

    Mirrors the `---\\n` splitting used by scraper.extract_frontmatter and
    scraper.extract_markdown_from_statement, but operates on a string so it can
    be reused for `git show` output (which never touches the filesystem).
    """
    parts = content.split("---\n", 2)
    if len(parts) >= 3:
        return (yaml.safe_load(parts[1]) or {}, parts[2].strip())
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


# --- artifact builders ------------------------------------------------------


def build_statement_doc(abbr: str, frontmatter: dict, body: str) -> dict:
    """Per-statement document (timeline/originality/neighbours/passages added later)."""
    doc: dict = {
        "abbr": abbr,
        "agency": frontmatter.get("agency", abbr),
        "title": frontmatter.get("title", f"{abbr} AI transparency statement"),
        "sourceUrl": frontmatter.get("source_url"),
        "sourceType": source_type(frontmatter),
        "body": body,
        "frontmatter": frontmatter,
    }
    if frontmatter.get("final_url"):
        doc["finalUrl"] = frontmatter["final_url"]
    return doc


def build_agency_index(records: list[dict], statements: dict[str, dict]) -> list[dict]:
    """Index of every agency with coverage status, sorted by abbr."""
    index = []
    for rec in records:
        abbr = rec["abbr"]
        has_statement = abbr in statements
        index.append(
            {
                "abbr": abbr,
                "name": rec["name"],
                "size": rec["size"],
                "url": rec["url"],
                "status": statement_status(abbr, rec["url"], has_statement),
                "statementId": abbr if has_statement else None,
            }
        )
    return sorted(index, key=lambda a: a["abbr"])


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

    agency_index = build_agency_index(records, statements)
    statuses = [a["status"] for a in agency_index]

    statement_docs = {
        abbr: build_statement_doc(abbr, data["frontmatter"], data["body"])
        for abbr, data in statements.items()
    }

    head_sha = git("rev-parse", "HEAD")
    meta = {
        "headSha": head_sha,
        "builtAt": datetime.now(UTC).isoformat(),
        "counts": {
            "agencies": len(records),
            "published": statuses.count("published"),
            "notYet": statuses.count("not-yet"),
            "exempt": statuses.count("exempt"),
            "statements": len(statements),
        },
    }

    write_json(GENERATED_DIR / "agencies.json", {"agencies": agency_index})
    for abbr, doc in statement_docs.items():
        write_json(GENERATED_DIR / "statements" / f"{abbr}.json", doc)
    write_json(GENERATED_DIR / "meta.json", meta)

    logger.info(
        "Exported: %d agencies (%d published, %d not-yet, %d exempt), %d statements",
        meta["counts"]["agencies"],
        meta["counts"]["published"],
        meta["counts"]["notYet"],
        meta["counts"]["exempt"],
        meta["counts"]["statements"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
