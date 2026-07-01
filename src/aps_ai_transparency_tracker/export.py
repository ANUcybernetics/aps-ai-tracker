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
directional "agency A copied from B". The most it infers is temporal: which
tracked statement *first observed* a shared passage (`firstObserved`), which is
"first seen by us" — never proof of authorship, since a passage may predate the
corpus. It also marks passages that appear in the DTA template (`alsoInDta`),
defensible because the DTA publishes the canonical policy.
"""

import hashlib
import json
import re
import subprocess
import sys
import tomllib
from collections import Counter, defaultdict
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
    """First-seen events: 'tracked-since' if bulk-imported, else 'added'.

    A first sighting only tells us when the statement entered the tracker, not
    when the agency published it (which we can't know), so neither first-seen
    kind claims a publication date: a statement from the day-one bulk-migration
    commit is 'tracked-since', one we began tracking later is 'added'. Every
    subsequent change is an 'updated' event (even if it rode in on a mass
    re-scrape — that is still real content change, so it is NOT marked
    tracked-since).
    """
    if index == 0:
        return "tracked-since" if rev.bulk else "added"
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


# --- passage propagation (lexical) ------------------------------------------

# Propagation is literal text reuse, so it is detected lexically (not via
# embeddings). Exact normalised clustering catches verbatim boilerplate; a
# canonical-phrase pass recovers the policy sentence that exact matching misses
# because it hides inside differently-worded host sentences.
CANONICAL_PHRASES = {
    "responsible-use": "responsible use of ai in government",
    "accountable-official": "accountable official",
}

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_NAV_RE = re.compile(
    r"(?i)\(opens in a new tab(?:/window)?\)|back to top(?: of the page)?"
)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
_LEADING_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+\.|#{1,6})\s*")
_MIN_NORM_CHARS = 25
_MIN_WORDS = 4
# Boilerplate = a passage shared verbatim by at least this many agencies.
_BOILERPLATE_MIN_AGENCIES = 2


@dataclass(frozen=True, slots=True)
class Passage:
    """One atomic passage of a statement body, with its normalised form."""

    abbr: str
    raw_text: str
    normalised: str
    norm_key: str
    kind: str  # paragraph | list_item | heading


def normalise_passage(text: str) -> str:
    """Canonicalise a passage for matching: drop links/markup/punctuation/case."""
    t = _MD_LINK_RE.sub(r"\1", text)
    t = _NAV_RE.sub(" ", t)
    t = _LEADING_MARKER_RE.sub("", t)
    t = re.sub(r"[*_`~]", "", t)
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return _WS_RE.sub(" ", t).strip()


def _norm_key(normalised: str) -> str:
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def contains_canonical_phrase(normalised: str) -> bool:
    return any(phrase in normalised for phrase in CANONICAL_PHRASES.values())


def _split_list_items(lines: list[str]) -> list[str]:
    """Group list lines into items, attaching continuation lines to their marker."""
    items: list[str] = []
    current: list[str] = []
    for line in lines:
        if _LIST_ITEM_RE.match(line):
            if current:
                items.append("\n".join(current))
            current = [line]
        elif line.strip() and current:
            current.append(line)
    if current:
        items.append("\n".join(current))
    return items


def segment_passages(body: str, abbr: str) -> list[Passage]:
    """Split a body into paragraph / list-item / heading passages, dropping stubs."""
    passages: list[Passage] = []

    def add(raw: str, kind: str) -> None:
        raw = raw.strip()
        normalised = normalise_passage(raw)
        if len(normalised) >= _MIN_NORM_CHARS and len(normalised.split()) >= _MIN_WORDS:
            passages.append(Passage(abbr, raw, normalised, _norm_key(normalised), kind))

    for block in re.split(r"\n\s*\n", body.strip()):
        block = block.strip()
        if not block:
            continue
        first = block.splitlines()[0]
        if _LIST_ITEM_RE.match(first):
            for item in _split_list_items(block.splitlines()):
                add(item, "list_item")
        elif _HEADING_RE.match(first):
            add(block, "heading")
        else:
            add(block, "paragraph")
    return passages


def _modal(values: list[str]) -> str:
    """Most frequent value, breaking ties lexicographically for determinism."""
    counts = Counter(values)
    return min(counts, key=lambda v: (-counts[v], v))


def first_seen_passages(
    timelines: dict[str, list[Revision]],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], str | None]:
    """Earliest date each agency's history shows a given passage / template phrase.

    Walks every de-noised revision oldest-first, recording for each agency the
    first date a passage's `norm_key` — and each canonical phrase — is observed.
    These feed every shared-passage cluster's "first observed in our corpus"
    provenance. Also returns the corpus start: the earliest first-tracked date
    across all statements (the moment continuous tracking begins).

    This is "first observed by us", never "authored first": a passage present at
    an agency's first tracked revision may predate the corpus entirely.
    """
    by_key: dict[str, dict[str, str]] = {}
    by_phrase: dict[str, dict[str, str]] = {}
    corpus_start: str | None = None
    for abbr, revisions in timelines.items():
        keys: dict[str, str] = {}
        phrases: dict[str, str] = {}
        for index, rev in enumerate(revisions):
            if index == 0 and (
                corpus_start is None
                or datetime.fromisoformat(rev.date)
                < datetime.fromisoformat(corpus_start)
            ):
                corpus_start = rev.date
            passages = segment_passages(rev.body, abbr)
            for passage in passages:
                keys.setdefault(passage.norm_key, rev.date)
            blob = "\n".join(p.normalised for p in passages)
            for phrase_id, phrase in CANONICAL_PHRASES.items():
                if phrase in blob:
                    phrases.setdefault(phrase_id, rev.date)
        by_key[abbr] = keys
        by_phrase[abbr] = phrases
    return by_key, by_phrase, corpus_start


# How far past the corpus start a passage's earliest sighting must fall before we
# treat that agency as having genuinely *added* it (rather than carrying it in at
# tracking start, which says nothing about who came first).
_FIRST_OBSERVED_GRACE_DAYS = 2


def _first_observed(
    members: list[str],
    first_seen: dict[str, dict[str, str]],
    key: str,
    corpus_start: str | None,
) -> dict | None:
    """First-observed provenance for one cluster: who carried the passage earliest.

    Returns the per-member first-seen dates (oldest first), the single earliest
    agency, and a tier describing how much weight the ordering bears:

    - ``added``: the earliest agency first showed the passage well after the
      corpus opened, so we watched it enter — the strongest signal.
    - ``present-at-start``: the earliest agency already had it when tracking
      began; others adopted it later, but its own origin may predate the corpus.
    - ``tied``: several agencies share the earliest date, so we cannot order them.

    Still only "first observed by us", never proof of authorship.
    """
    seen = sorted(
        ((first_seen[a][key], a) for a in members if key in first_seen.get(a, {})),
        key=lambda da: (datetime.fromisoformat(da[0]), da[1]),
    )
    if len(seen) < 2:
        return None
    earliest = datetime.fromisoformat(seen[0][0])
    winners = [a for d, a in seen if datetime.fromisoformat(d) == earliest]
    if len(winners) > 1:
        tier = "tied"
    elif (
        corpus_start
        and (earliest - datetime.fromisoformat(corpus_start)).days
        > _FIRST_OBSERVED_GRACE_DAYS
    ):
        tier = "added"
    else:
        tier = "present-at-start"
    return {
        "abbr": winners[0] if len(winners) == 1 else None,
        "date": seen[0][0],
        "tier": tier,
        "order": [{"abbr": a, "date": d} for d, a in seen],
    }


def build_clusters(
    passages_by_abbr: dict[str, list[Passage]],
    dta_abbr: str = "DTA",
    first_seen_key: dict[str, dict[str, str]] | None = None,
    first_seen_phrase: dict[str, dict[str, str]] | None = None,
    corpus_start: str | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Cluster shared passages and return (clusters, sharedCount-by-norm_key).

    Clusters assert co-occurrence, plus two defensible extras: `alsoInDta`
    (template overlap) and `firstObserved` (which tracked statement showed the
    passage earliest — "first seen by us", not authorship; see `_first_observed`).
    """
    groups: dict[str, list[Passage]] = defaultdict(list)
    for passages in passages_by_abbr.values():
        for passage in passages:
            groups[passage.norm_key].append(passage)

    shared_count = {key: len({p.abbr for p in group}) for key, group in groups.items()}

    clusters: list[dict] = []
    for key, group in groups.items():
        members = sorted({p.abbr for p in group})
        if len(members) < _BOILERPLATE_MIN_AGENCIES:
            continue
        clusters.append(
            {
                "normKey": key,
                "canonicalText": _modal([p.raw_text for p in group]),
                "kind": _modal([p.kind for p in group]),
                "memberAbbrs": members,
                "count": len(members),
                "alsoInDta": dta_abbr in members,
                "containsCanonicalPhrase": contains_canonical_phrase(
                    group[0].normalised
                ),
                "firstObserved": (
                    _first_observed(members, first_seen_key, key, corpus_start)
                    if first_seen_key is not None
                    else None
                ),
                "mergeMethod": "exact",
            }
        )

    # Canonical-phrase clusters: agencies whose text contains a template phrase,
    # however it is worded. Recovers the policy sentence exact matching misses.
    for phrase_id, phrase in CANONICAL_PHRASES.items():
        members = sorted(
            abbr
            for abbr, passages in passages_by_abbr.items()
            if any(phrase in p.normalised for p in passages)
        )
        if len(members) < _BOILERPLATE_MIN_AGENCIES:
            continue
        clusters.append(
            {
                "normKey": f"phrase:{phrase_id}",
                "canonicalText": _phrase_example(
                    passages_by_abbr, members, phrase, dta_abbr
                ),
                "kind": "phrase",
                "memberAbbrs": members,
                "count": len(members),
                "alsoInDta": dta_abbr in members,
                "containsCanonicalPhrase": True,
                "firstObserved": (
                    _first_observed(
                        members, first_seen_phrase, phrase_id, corpus_start
                    )
                    if first_seen_phrase is not None
                    else None
                ),
                "mergeMethod": "phrase",
            }
        )

    clusters.sort(key=lambda c: (-c["count"], c["normKey"]))
    return clusters, shared_count


def _phrase_example(
    passages_by_abbr: dict[str, list[Passage]],
    members: list[str],
    phrase: str,
    dta_abbr: str,
) -> str:
    """A representative raw passage containing `phrase`, preferring the DTA template."""
    order = [dta_abbr, *members] if dta_abbr in members else members
    for abbr in order:
        for passage in passages_by_abbr.get(abbr, []):
            if phrase in passage.normalised:
                return passage.raw_text
    return phrase


def statement_passages(
    passages: list[Passage], shared_count: dict[str, int]
) -> list[dict]:
    """Per-statement passage rows (document order) powering the heat-map + browser."""
    rows = []
    for passage in passages:
        count = shared_count.get(passage.norm_key, 1)
        rows.append(
            {
                "normKey": passage.norm_key,
                "kind": passage.kind,
                "rawText": passage.raw_text,
                "sharedCount": count,
                "isBoilerplate": count >= _BOILERPLATE_MIN_AGENCIES,
                "containsCanonicalPhrase": contains_canonical_phrase(
                    passage.normalised
                ),
            }
        )
    return rows


def _is_shared(passage: Passage, shared_count: dict[str, int]) -> bool:
    """A passage is boilerplate if shared verbatim or carrying template language."""
    return shared_count.get(passage.norm_key, 1) >= _BOILERPLATE_MIN_AGENCIES or (
        contains_canonical_phrase(passage.normalised)
    )


def originality_score(passages: list[Passage], shared_count: dict[str, int]) -> dict:
    """Length-weighted share of a statement that is bespoke vs template/boilerplate.

    Score 1.0 = wholly unique, low = mostly copied. DTA scores low *because* it is
    the template source, so the site labels it canonical rather than unoriginal.
    """
    total = sum(len(p.normalised) for p in passages)
    if total == 0:
        return {
            "score": 1.0,
            "sharedChars": 0,
            "totalChars": 0,
            "unique": 0,
            "shared": 0,
        }
    shared = [p for p in passages if _is_shared(p, shared_count)]
    shared_chars = sum(len(p.normalised) for p in shared)
    return {
        "score": round(1 - shared_chars / total, 4),
        "sharedChars": shared_chars,
        "totalChars": total,
        "unique": len(passages) - len(shared),
        "shared": len(shared),
    }


# --- embeddings + similarity (OpenAI) ---------------------------------------

EMBED_MODEL = "text-embedding-3-small"
CACHE_PATH = REPO_ROOT / ".cache" / "embeddings.json"
_NEIGHBOURS = 8
# Graph edges come from each node's top few neighbours, not a global cosine
# threshold: government statements share so much vocabulary that any fixed floor
# produces a hairball. A k-nearest-neighbour graph stays legible.
_GRAPH_NEIGHBOURS = 3
# The embedding endpoint caps inputs at 8192 tokens, and one bad input fails the
# whole batch. Truncate to a safe char budget (~3.5 chars/token); the opening of
# a statement is plenty to characterise it for similarity. The cache key is still
# the full-body hash, so a statement re-embeds only when its real text changes.
_MAX_EMBED_CHARS = 24000
# numpy/openai live in the optional `export` group, so they are imported lazily:
# the timeline/passage/originality artifacts must still build without them.


def content_hash(body: str) -> str:
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_embedding_cache(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_embedding_cache(path: Path, cache: dict) -> None:
    """Write one statement per line so a changed statement is a one-line git diff."""
    path.parent.mkdir(parents=True, exist_ok=True)
    items = sorted(cache.items())
    lines = ["{"]
    for i, (key, value) in enumerate(items):
        tail = "," if i < len(items) - 1 else ""
        lines.append(
            f"  {json.dumps(key)}: {json.dumps(value, separators=(',', ':'))}{tail}"
        )
    lines.append("}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def embed_statements(
    bodies: dict[str, str], cache: dict
) -> tuple[dict[str, list], bool]:
    """Return {abbr: vector} for whatever can be embedded; (vectors, api_called).

    Only cache misses hit the API, so the typical daily build makes zero calls.
    Missing key or API failure degrades to the cache rather than failing the build.
    """
    import os

    need = {abbr: b for abbr, b in bodies.items() if content_hash(b) not in cache}
    api_called = False
    if need and not os.environ.get("OPENAI_API_KEY"):
        logger.warning(
            "OPENAI_API_KEY absent; %d statements have no embedding (cache covers %d)",
            len(need),
            len(bodies) - len(need),
        )
    elif need:
        try:
            from openai import OpenAI, OpenAIError

            client = OpenAI()
            items = sorted(need.items())
            response = client.embeddings.create(
                model=EMBED_MODEL, input=[body[:_MAX_EMBED_CHARS] for _, body in items]
            )
            for (_, body), datum in zip(items, response.data, strict=True):
                cache[content_hash(body)] = {
                    "model": EMBED_MODEL,
                    "dim": len(datum.embedding),
                    "vector": [float(f"{x:.7g}") for x in datum.embedding],
                }
            api_called = True
            logger.info("Embedded %d new statements via %s", len(items), EMBED_MODEL)
        except OpenAIError as exc:
            logger.warning("Embedding API failed (%s); falling back to cache", exc)
    vectors = {
        abbr: cache[content_hash(body)]["vector"]
        for abbr, body in bodies.items()
        if content_hash(body) in cache
    }
    return vectors, api_called


def cosine_neighbours(
    vectors: dict[str, list], k: int = _NEIGHBOURS
) -> tuple[dict[str, list], list[dict]]:
    """Top-k nearest neighbours per statement + a thresholded, deduped edge list."""
    if not vectors:
        return {}, []
    import numpy as np

    abbrs = sorted(vectors)
    matrix = np.asarray([vectors[a] for a in abbrs], dtype=np.float64)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    sims = matrix @ matrix.T
    np.fill_diagonal(sims, -np.inf)

    neighbours = {}
    for i, abbr in enumerate(abbrs):
        top = np.argsort(-sims[i])[:k]
        neighbours[abbr] = [
            {"abbr": abbrs[j], "score": round(float(sims[i, j]), 4)} for j in top
        ]

    seen: set[tuple[str, str]] = set()
    edges = []
    for abbr, neighs in neighbours.items():
        for n in neighs[:_GRAPH_NEIGHBOURS]:
            key = (abbr, n["abbr"]) if abbr < n["abbr"] else (n["abbr"], abbr)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"a": key[0], "b": key[1], "score": n["score"]})
    edges.sort(key=lambda e: (-e["score"], e["a"], e["b"]))
    return neighbours, edges


def compute_similarity(
    bodies: dict[str, str], sizes: dict[str, str], originalities: dict[str, dict]
) -> tuple[dict, dict, dict[str, list]]:
    """Build similarity.json, the slim graph, and per-statement neighbour lists."""
    cache = load_embedding_cache(CACHE_PATH)
    vectors, api_called = embed_statements(bodies, cache)
    if api_called:
        save_embedding_cache(CACHE_PATH, cache)

    neighbours, edges = cosine_neighbours(vectors)
    abbrs = sorted(vectors)
    similarity = {
        "model": EMBED_MODEL,
        "k": _NEIGHBOURS,
        "abbrs": abbrs,
        "neighbours": neighbours,
        "edges": edges,
    }
    graph = {
        "nodes": [
            {
                "id": abbr,
                "abbr": abbr,
                "size": sizes.get(abbr, "unknown"),
                "originality": originalities[abbr]["score"],
            }
            for abbr in abbrs
        ],
        "edges": edges,
    }
    return similarity, graph, neighbours


# --- artifact builders ------------------------------------------------------


def build_statement_doc(
    abbr: str,
    frontmatter: dict,
    body: str,
    timeline: list[dict],
    passages: list[dict],
    originality: dict,
    neighbours: list[dict],
) -> dict:
    """Per-statement document consumed by the statement page."""
    doc: dict = {
        "abbr": abbr,
        "agency": frontmatter.get("agency", abbr),
        "title": frontmatter.get("title", f"{abbr} AI transparency statement"),
        "sourceUrl": frontmatter.get("source_url"),
        "sourceType": source_type(frontmatter),
        "body": body,
        "frontmatter": frontmatter,
        "timeline": timeline,
        "passages": passages,
        "originality": originality,
        "neighbours": neighbours,
    }
    if frontmatter.get("final_url"):
        doc["finalUrl"] = frontmatter["final_url"]
    return doc


def build_agency_index(
    records: list[dict],
    statements: dict[str, dict],
    timelines: dict[str, list[Revision]],
    originalities: dict[str, dict],
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
                "originality": originalities[abbr]["score"] if has_statement else None,
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

    timeline = build_timeline(timelines, records, statements)

    first_seen_key, first_seen_phrase, corpus_start = first_seen_passages(timelines)

    passages_by_abbr = {
        abbr: segment_passages(data["body"], abbr) for abbr, data in statements.items()
    }
    clusters, shared_count = build_clusters(
        passages_by_abbr,
        first_seen_key=first_seen_key,
        first_seen_phrase=first_seen_phrase,
        corpus_start=corpus_start,
    )
    originalities = {
        abbr: originality_score(passages, shared_count)
        for abbr, passages in passages_by_abbr.items()
    }
    leaderboard = sorted(
        ({"abbr": abbr, "score": o["score"]} for abbr, o in originalities.items()),
        key=lambda e: (-e["score"], e["abbr"]),
    )

    logger.info("Computing statement similarity...")
    sizes = {r["abbr"]: r["size"] for r in records}
    bodies = {abbr: data["body"] for abbr, data in statements.items()}
    similarity, graph, neighbours = compute_similarity(bodies, sizes, originalities)

    agency_index = build_agency_index(records, statements, timelines, originalities)
    statuses = [a["status"] for a in agency_index]

    statement_docs = {
        abbr: build_statement_doc(
            abbr,
            data["frontmatter"],
            data["body"],
            timeline_entries(timelines[abbr]),
            statement_passages(passages_by_abbr[abbr], shared_count),
            originalities[abbr],
            neighbours.get(abbr, []),
        )
        for abbr, data in statements.items()
    }

    first_commit = git("log", "--reverse", "--format=%aI", "--max-parents=0")
    meta = {
        "headSha": git("rev-parse", "HEAD"),
        "builtAt": datetime.now(UTC).isoformat(),
        "firstCommit": first_commit.splitlines()[0] if first_commit else None,
        "corpusStart": corpus_start,
        "apiUsed": bool(similarity["abbrs"]),
        "counts": {
            "agencies": len(records),
            "published": statuses.count("published"),
            "notYet": statuses.count("not-yet"),
            "exempt": statuses.count("exempt"),
            "statements": len(statements),
            "revisions": total_revisions,
            "embedded": len(similarity["abbrs"]),
        },
    }

    write_json(GENERATED_DIR / "agencies.json", {"agencies": agency_index})
    write_json(GENERATED_DIR / "timeline.json", {"events": timeline})
    write_json(
        GENERATED_DIR / "propagation.json",
        {"clusters": clusters, "originality": leaderboard, "ursource": "DTA"},
    )
    write_json(GENERATED_DIR / "similarity.json", similarity)
    write_json(PUBLIC_DATA_DIR / "similarity.graph.json", graph)
    for abbr, doc in statement_docs.items():
        write_json(GENERATED_DIR / "statements" / f"{abbr}.json", doc)
    write_json(GENERATED_DIR / "meta.json", meta)

    logger.info(
        "Exported: %d agencies (%d published, %d not-yet, %d exempt), "
        "%d statements, %d timeline events, %d clusters, %d embedded",
        meta["counts"]["agencies"],
        meta["counts"]["published"],
        meta["counts"]["notYet"],
        meta["counts"]["exempt"],
        meta["counts"]["statements"],
        len(timeline),
        len(clusters),
        len(similarity["abbrs"]),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
