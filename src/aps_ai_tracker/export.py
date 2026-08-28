"""Export the statement corpus + git history as JSON for the static site.

Reads `agencies.toml`, the `statements/*.md` corpus, and the git history, and
writes a set of JSON artifacts under `site/src/generated/` that the Astro site
consumes at build time.

The artifacts are fully derivable from the repo plus the committed Claude
extraction caches (`.cache/changes.json`, `.cache/profiles.json`), so they are
gitignored and regenerated in CI without any model calls. All JSON is written deterministically (sorted keys, rounded floats)
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
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .adoption import build_adoption, staleness
from .changes import UNCLASSIFIED, Classification, classify_pairs
from .profiles import (
    Profile,
    Step,
    delta_dict,
    diff_profiles,
    extract_profiles,
    standard_report,
)
from .scraper import (
    REPO_ROOT,
    Agency,
    atomic_write_text,
    load_agencies,
    logger,
    split_frontmatter_body,
)

STATEMENTS_DIR = REPO_ROOT / "statements"
GENERATED_DIR = REPO_ROOT / "site" / "src" / "generated"


# --- small shared helpers ---------------------------------------------------


# Generous for a local repo (the slowest call here is a full-history --name-only
# log, well under a second). The point is that a hung git — lock contention, a
# network-mounted repo — fails the nightly export loudly instead of stalling it
# until the systemd TimeoutStartSec kills the whole run.
_GIT_TIMEOUT_SECONDS = 120


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
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    return result.stdout.strip("\n")


def write_json(path: Path, obj: object) -> None:
    """Write `obj` as deterministic, human-diffable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path, json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


# --- loading ----------------------------------------------------------------


def statement_status(scope: str, url: str | None, has_statement: bool) -> str:
    """Classify an agency as published / not-yet / exempt.

    `scope` comes from agencies.toml and records what the Policy for the
    responsible use of AI in government actually asks of the body: `mandatory`
    for non-corporate Commonwealth entities, `voluntary` for corporate entities
    and bodies outside the PGPA list, `exempt` for the defence portfolio and the
    national intelligence community. An agency that owes a statement and has
    none reads as not-yet; so does one we hold a URL for but failed to capture
    this run. Only bodies with no obligation and no statement read as exempt.
    """
    if has_statement:
        return "published"
    if scope == "mandatory" or url is not None:
        return "not-yet"
    return "exempt"


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
    r"(?i)spurious|nav-tile|nav-card|nav-chrome|related-pages|download-widget|"
    r"cleanup-pipeline|leaked into the diff|go to section"
)

_WS_RE = re.compile(r"\s+")
_INLINE_LINK_RE = re.compile(r"(!?)\[([^]]*)\]\((?:[^()\\]|\\.|\([^)]*\))*\)")
_STANDALONE_LINK_RE = re.compile(
    r"(?m)^\s*(?:[-*+]\s+)?!?\[[^]]*\]\((?:[^()\\]|\\.|\([^)]*\))*\)\s*$"
)
_REFERENCE_LINK_RE = re.compile(r"(?m)^(\s*\[[^]]+\]:)\s*\S+.*$")


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
    # No --follow: statement files are never renamed (the path is the agency key),
    # and git's copy detection happily traces a new statement back through an
    # unrelated agency's history when the boilerplate is similar enough — which
    # both misattributes the timeline and breaks the `git show sha:rel` below.
    raw = git(
        "log",
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


def _without_link_changes(body: str) -> str:
    """Project Markdown to statement text, ignoring link-only page churn."""
    body = _STANDALONE_LINK_RE.sub("", body)
    body = _INLINE_LINK_RE.sub(lambda match: f"{match[1]}[{match[2]}]()", body)
    body = _REFERENCE_LINK_RE.sub(r"\1", body)
    return _WS_RE.sub(" ", body).strip()


def is_noise_revision(rev: Revision, previous: Revision | None = None) -> bool:
    """Whether a revision is annotated noise or changes only Markdown links."""
    annotated = bool(_NOISE_RE.search(rev.subject) or _NOISE_RE.search(rev.message))
    link_only = previous is not None and _without_link_changes(
        previous.body
    ) == _without_link_changes(rev.body)
    return annotated or link_only


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


def classify_timelines(
    timelines: dict[str, list[Revision]], names: dict[str, str]
) -> dict[str, dict[str, Classification]]:
    """Content-based change classification for every consecutive revision pair.

    Returns {abbr: {sha: Classification}} for every revision after the first.
    """
    pairs = {
        f"{abbr}:{rev.sha}": (names.get(abbr, abbr), revs[i - 1].body, rev.body)
        for abbr, revs in timelines.items()
        for i, rev in enumerate(revs)
        if i > 0
    }
    classified = classify_pairs(pairs)
    out: dict[str, dict[str, Classification]] = defaultdict(dict)
    for pair_id, classification in classified.items():
        abbr, sha = pair_id.split(":", 1)
        out[abbr][sha] = classification
    return out


def profile_timelines(
    timelines: dict[str, list[Revision]],
    classes: dict[str, dict[str, Classification]],
    names: dict[str, str],
) -> dict[str, list[Profile | None]]:
    """One profile per revision: read for readable revisions, inherited across noise.

    The first revision and every non-noise revision are read (each anchored on
    the previous profile); a noise revision (nothing the agency wrote changed)
    carries its predecessor's profile forward.
    """
    chains = {
        abbr: (
            names.get(abbr, abbr),
            [
                Step(
                    body=rev.body,
                    readable=i == 0
                    or (c := classes.get(abbr, {}).get(rev.sha)) is None
                    or not c.is_noise,
                )
                for i, rev in enumerate(revs)
            ],
        )
        for abbr, revs in timelines.items()
    }
    return extract_profiles(chains)


def _profile_deltas(
    index: int,
    rev: Revision,
    classes: dict[str, Classification],
    profiles: list[Profile | None],
) -> list[dict]:
    """Structured field-level changes for a revision that changed the substance.

    Deltas are reported only where the diff-based classification agrees the
    substance changed (content kinds, or an unclassified pair); a cosmetic or
    noise revision's profile may still move (a stated date, say) but is not
    shown as a change of substance.
    """
    if index == 0 or not profiles:
        return []
    c = classes.get(rev.sha)
    if c is None or not (c.is_content or c.kind == UNCLASSIFIED):
        return []
    before, after = profiles[index - 1], profiles[index]
    if before is None or after is None:
        return []
    return [delta_dict(d) for d in diff_profiles(before, after)]


def _change_fields(
    index: int,
    rev: Revision,
    revisions: list[Revision],
    classes: dict[str, Classification],
) -> dict:
    """Change-kind fields shared by the per-statement and site-wide timelines.

    `isNoise` prefers the content-based classification; an unclassified pair
    (no API key and no cache entry) falls back to the commit-message heuristic.
    """
    if index == 0:
        return {
            "changeKind": "first-seen",
            "changeMethod": "rule",
            "summary": None,
            "noteworthy": [],
            "isNoise": False,
        }
    c = classes.get(rev.sha, Classification(kind=UNCLASSIFIED, method="uncached"))
    return {
        "changeKind": c.kind,
        "changeMethod": c.method,
        "summary": c.summary,
        "noteworthy": c.noteworthy,
        "isNoise": (
            c.is_noise
            if c.kind != UNCLASSIFIED
            else is_noise_revision(rev, revisions[index - 1])
        ),
    }


def timeline_entries(
    revisions: list[Revision],
    classes: dict[str, Classification] | None = None,
    profiles: list[Profile | None] | None = None,
) -> list[dict]:
    """Per-statement timeline rows (full body included for build-time diffing)."""
    classes = classes or {}
    profiles = profiles or []
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
                **_change_fields(i, rev, revisions, classes),
                "profileDeltas": _profile_deltas(i, rev, classes, profiles),
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
                    _first_observed(members, first_seen_phrase, phrase_id, corpus_start)
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


# --- artifact builders ------------------------------------------------------


def build_statement_doc(
    abbr: str,
    frontmatter: dict,
    body: str,
    timeline: list[dict],
    passages: list[dict],
    originality: dict,
    profile: Profile | None = None,
    currency: dict | None = None,
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
        "profile": profile.model_dump(mode="json") if profile else None,
        "standard": standard_report(profile) if profile else None,
        "currency": currency,
    }
    if frontmatter.get("final_url"):
        doc["finalUrl"] = frontmatter["final_url"]
    return doc


def build_agency_index(
    agencies: list[Agency],
    statements: dict[str, dict],
    timelines: dict[str, list[Revision]],
    originalities: dict[str, dict],
    currencies: dict[str, dict] | None = None,
) -> list[dict]:
    """Index of every agency with coverage status + revision summary, sorted by abbr."""
    currencies = currencies or {}
    index = []
    for agency in agencies:
        abbr = agency.abbr
        has_statement = abbr in statements
        revs = timelines.get(abbr, [])
        index.append(
            {
                "abbr": abbr,
                "name": agency.name,
                "size": agency.size,
                "scope": agency.scope,
                "portfolio": agency.portfolio,
                "url": agency.url,
                "status": statement_status(agency.scope, agency.url, has_statement),
                "statementId": abbr if has_statement else None,
                "firstSeen": revs[0].date if revs else None,
                "lastUpdated": revs[-1].date if revs else None,
                "revisionCount": len(revs),
                "originality": originalities[abbr]["score"] if has_statement else None,
                "currency": currencies.get(abbr),
            }
        )
    return sorted(index, key=lambda a: a["abbr"])


def build_timeline(
    timelines: dict[str, list[Revision]],
    agencies: list[Agency],
    statements: dict[str, dict],
    classes: dict[str, dict[str, Classification]] | None = None,
) -> list[dict]:
    """Flat, reverse-chronological feed of every change event (no bodies)."""
    sizes = {a.abbr: a.size for a in agencies}
    classes = classes or {}
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
                    "commitSubject": rev.subject,
                    "kind": _event_kind(i, rev),
                    **_change_fields(i, rev, revs, classes.get(abbr, {})),
                }
            )
    return sorted(events, key=lambda e: (e["date"], e["id"]), reverse=True)


def load_statements() -> dict[str, dict]:
    """Read every statements/*.md into {abbr: {frontmatter, body}}.

    A statement that can't be parsed is an error, not a skip: silently dropping
    it would flip the agency to "not-yet" on the site and assert something false.
    """
    statements: dict[str, dict] = {}
    for path in sorted(STATEMENTS_DIR.glob("*.md")):
        frontmatter, body = split_frontmatter_body(path.read_text(encoding="utf-8"))
        if frontmatter is None or not body:
            raise ValueError(f"Could not parse statement file {path}")
        statements[path.stem] = {"frontmatter": frontmatter, "body": body}
    return statements


def main() -> int:
    """Generate the JSON artifacts the static site consumes."""
    if not STATEMENTS_DIR.exists():
        logger.error("Error: %s directory not found", STATEMENTS_DIR)
        return 1

    logger.info("Starting export at %s", datetime.now(UTC).isoformat())

    agencies = load_agencies()
    statements = load_statements()
    logger.info("Loaded %d agencies, %d statements", len(agencies), len(statements))

    logger.info("Walking git history for %d statements...", len(statements))
    bulk = bulk_import_shas()
    timelines = {
        abbr: collapse_reverts(git_file_revisions(abbr, bulk)) for abbr in statements
    }
    total_revisions = sum(len(r) for r in timelines.values())

    names = {
        abbr: d["frontmatter"].get("agency", abbr) for abbr, d in statements.items()
    }
    logger.info("Classifying revision changes...")
    classes = classify_timelines(timelines, names)
    timeline = build_timeline(timelines, agencies, statements, classes)

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

    built_at = datetime.now(UTC).isoformat()
    logger.info("Extracting statement profiles...")
    profiles = profile_timelines(timelines, classes, names)
    currencies = {}
    for abbr, revs in timelines.items():
        content_dates = [
            rev.date
            for rev in revs
            if (c := classes.get(abbr, {}).get(rev.sha)) is not None and c.is_content
        ]
        currencies[abbr] = staleness(
            profiles[abbr][-1] if profiles[abbr] else None,
            content_dates[-1] if content_dates else None,
            revs[0].date,
            built_at,
        )
    adoption = build_adoption(
        {
            abbr: [
                (
                    rev.date,
                    rev.sha,
                    (c := classes.get(abbr, {}).get(rev.sha)) is not None
                    and c.is_noise,
                    profiles[abbr][i],
                )
                for i, rev in enumerate(revs)
            ]
            for abbr, revs in timelines.items()
        },
        corpus_start or built_at,
        built_at,
    )

    agency_index = build_agency_index(
        agencies, statements, timelines, originalities, currencies
    )
    statuses = [a["status"] for a in agency_index]

    statement_docs = {
        abbr: build_statement_doc(
            abbr,
            data["frontmatter"],
            data["body"],
            timeline_entries(timelines[abbr], classes.get(abbr, {}), profiles[abbr]),
            statement_passages(passages_by_abbr[abbr], shared_count),
            originalities[abbr],
            profiles[abbr][-1] if profiles[abbr] else None,
            currencies[abbr],
        )
        for abbr, data in statements.items()
    }

    first_commit = git("log", "--reverse", "--format=%aI", "--max-parents=0")
    meta = {
        "headSha": git("rev-parse", "HEAD"),
        "builtAt": built_at,
        "firstCommit": first_commit.splitlines()[0] if first_commit else None,
        "corpusStart": corpus_start,
        "counts": {
            "agencies": len(agencies),
            "published": statuses.count("published"),
            "notYet": statuses.count("not-yet"),
            "exempt": statuses.count("exempt"),
            "statements": len(statements),
            "revisions": total_revisions,
            "profiled": sum(1 for p in profiles.values() if p and p[-1] is not None),
        },
    }

    write_json(GENERATED_DIR / "agencies.json", {"agencies": agency_index})
    write_json(GENERATED_DIR / "timeline.json", {"events": timeline})
    write_json(
        GENERATED_DIR / "propagation.json",
        {"clusters": clusters, "originality": leaderboard, "ursource": "DTA"},
    )
    write_json(GENERATED_DIR / "adoption.json", adoption)
    # Superseded artifact from the retired embeddings layer; a stale copy would
    # keep validating against nothing.
    (GENERATED_DIR / "similarity.json").unlink(missing_ok=True)
    statement_dir = GENERATED_DIR / "statements"
    for abbr, doc in statement_docs.items():
        write_json(statement_dir / f"{abbr}.json", doc)
    # Prune statements that have left the corpus. The site globs this directory,
    # so a stale file keeps building a page for an agency we no longer track.
    for path in statement_dir.glob("*.json"):
        if path.stem not in statement_docs:
            logger.info("Pruning stale statement export: %s", path.name)
            path.unlink()
    write_json(GENERATED_DIR / "meta.json", meta)

    logger.info(
        "Exported: %d agencies (%d published, %d not-yet, %d exempt), "
        "%d statements, %d timeline events, %d clusters, %d profiled",
        meta["counts"]["agencies"],
        meta["counts"]["published"],
        meta["counts"]["notYet"],
        meta["counts"]["exempt"],
        meta["counts"]["statements"],
        len(timeline),
        len(clusters),
        meta["counts"]["profiled"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
