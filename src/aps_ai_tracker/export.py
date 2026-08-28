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
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .adoption import build_adoption, staleness
from .changes import UNCLASSIFIED, Classification, classify_pairs
from .profiles import (
    Profile,
    Reading,
    Step,
    delta_dict,
    diff_profiles,
    extract_profiles,
    standard_report,
)
from .scraper import (
    CONTENT_SHRINKAGE_THRESHOLD,
    REPO_ROOT,
    Agency,
    atomic_write_text,
    load_agencies,
    logger,
    split_frontmatter_body,
)

STATEMENTS_DIR = REPO_ROOT / "statements"
GENERATED_DIR = REPO_ROOT / "site" / "src" / "generated"
CAPTURES_PATH = REPO_ROOT / "captures.toml"


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

_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Captures:
    """Operator verdicts on individual captures, from `captures.toml`.

    `quarantine` lists (abbr, sha) revisions that are failed captures — a page
    rendered client-side, a scraper regression — and must never be read as the
    agency changing its statement. `confirmed` lists revisions that shrank by
    more than half and are genuine, so the automatic shrink check lets them
    through. SHAs may be abbreviated prefixes.
    """

    quarantine: tuple[tuple[str, str], ...] = ()
    confirmed: tuple[tuple[str, str], ...] = ()

    @staticmethod
    def _listed(entries: tuple[tuple[str, str], ...], abbr: str, sha: str) -> bool:
        return any(a == abbr and sha.startswith(s) for a, s in entries)

    def is_quarantined(self, abbr: str, sha: str) -> bool:
        return self._listed(self.quarantine, abbr, sha)

    def is_confirmed(self, abbr: str, sha: str) -> bool:
        return self._listed(self.confirmed, abbr, sha)


def load_captures(path: Path = CAPTURES_PATH) -> Captures:
    if not path.exists():
        return Captures()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Captures(
        quarantine=tuple((d["abbr"], d["sha"]) for d in data.get("quarantine", [])),
        confirmed=tuple((d["abbr"], d["sha"]) for d in data.get("confirmed", [])),
    )


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


def quarantine_revisions(
    abbr: str, revisions: list[Revision], captures: Captures
) -> tuple[list[Revision], bool]:
    """Drop failed captures from a statement's history.

    Listed quarantine entries are dropped outright. The newest revision is also
    held back when its body is less than half its predecessor's
    (`CONTENT_SHRINKAGE_THRESHOLD`) and it is not confirmed genuine: a fresh
    capture that lost most of the page is far more often a scraper failure
    than an agency deleting most of its statement, and an unread revision is
    a missing entry, not a false claim. It stays held, with a warning each
    run, until the scraper is fixed or the shrink is confirmed. Older shrinks
    are left alone: the classifier has already read them (our own chrome
    stripping is a common, harmless cause) and the operator has had the
    warning. Returns the surviving revisions and whether the newest one was
    dropped (so the site can show the last good body instead).
    """
    kept = [r for r in revisions if not captures.is_quarantined(abbr, r.sha)]
    newest_dropped = bool(revisions) and (not kept or kept[-1] is not revisions[-1])
    if len(kept) >= 2:
        prev, newest = kept[-2], kept[-1]
        if len(newest.body) < len(
            prev.body
        ) * CONTENT_SHRINKAGE_THRESHOLD and not captures.is_confirmed(abbr, newest.sha):
            logger.warning(
                "%s %s shrank from %d to %d chars; held back as a failed capture. "
                "Add it to captures.toml under [[confirmed]] if it is genuine, "
                "or [[quarantine]] to settle it.",
                abbr,
                newest.sha[:10],
                len(prev.body),
                len(newest.body),
            )
            kept.pop()
            newest_dropped = True
    return kept, newest_dropped


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
    The diff is the only evidence: commit messages are not consulted, because
    a scrape commit's message describes the whole batch, not any one file
    (the nightly agent notes a noise regression in one statement's diff in a
    commit that also carries another agency's rewrite). A capture that is
    wrong belongs in `captures.toml`, not in a commit-message heuristic.
    """
    pairs = {
        f"{abbr}:{rev.sha}": (names.get(abbr, abbr), revs[i - 1].body, rev.body)
        for abbr, revs in timelines.items()
        for i, rev in enumerate(revs)
        if i > 0
    }
    out: dict[str, dict[str, Classification]] = defaultdict(dict)
    for pair_id, classification in classify_pairs(pairs).items():
        abbr, sha = pair_id.split(":", 1)
        out[abbr][sha] = classification
    return out


def profile_timelines(
    timelines: dict[str, list[Revision]],
    classes: dict[str, dict[str, Classification]],
    names: dict[str, str],
) -> dict[str, list[Reading]]:
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
    index: int, rev: Revision, classes: dict[str, Classification]
) -> dict:
    """Change-kind fields shared by the per-statement and site-wide timelines."""
    if index == 0:
        return {
            "changeKind": "first-seen",
            "changeMethod": "rule",
            "model": None,
            "summary": None,
            "noteworthy": [],
            "isNoise": False,
        }
    c = classes.get(rev.sha, Classification(kind=UNCLASSIFIED, method="uncached"))
    return {
        "changeKind": c.kind,
        "changeMethod": c.method,
        "model": c.model,
        "summary": c.summary,
        "noteworthy": c.noteworthy,
        "isNoise": c.is_noise,
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
                **_change_fields(i, rev, classes),
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


@dataclass(frozen=True, slots=True)
class FirstSeen:
    """Earliest dates in each agency's history, for passage provenance.

    `keys` and `phrases` map abbr → {norm_key / phrase id → first date observed};
    `tracked` maps abbr → the date its first revision entered the tracker.
    """

    keys: dict[str, dict[str, str]]
    phrases: dict[str, dict[str, str]]
    tracked: dict[str, str]

    @property
    def corpus_start(self) -> str | None:
        """The earliest first-tracked date: when continuous tracking began."""
        return min(self.tracked.values(), key=datetime.fromisoformat, default=None)


def first_seen_passages(timelines: dict[str, list[Revision]]) -> FirstSeen:
    """Earliest date each agency's history shows a given passage / template phrase.

    Walks every de-noised revision oldest-first, recording for each agency the
    first date a passage's `norm_key` — and each canonical phrase — is observed.
    These feed every shared-passage cluster's "first observed in our corpus"
    provenance.

    This is "first observed by us", never "authored first": a passage present at
    an agency's first tracked revision may predate the corpus entirely.
    """
    by_key: dict[str, dict[str, str]] = {}
    by_phrase: dict[str, dict[str, str]] = {}
    tracked: dict[str, str] = {}
    for abbr, revisions in timelines.items():
        keys: dict[str, str] = {}
        phrases: dict[str, str] = {}
        for index, rev in enumerate(revisions):
            if index == 0:
                tracked[abbr] = rev.date
            passages = segment_passages(rev.body, abbr)
            for passage in passages:
                keys.setdefault(passage.norm_key, rev.date)
            blob = "\n".join(p.normalised for p in passages)
            for phrase_id, phrase in CANONICAL_PHRASES.items():
                if phrase in blob:
                    phrases.setdefault(phrase_id, rev.date)
        by_key[abbr] = keys
        by_phrase[abbr] = phrases
    return FirstSeen(by_key, by_phrase, tracked)


# How far past an agency's own first tracked revision a passage's earliest
# sighting must fall before we treat that agency as having genuinely *added* it
# (rather than carrying it in at tracking start, which says nothing about who
# came first). Agencies join the corpus in waves, so this is measured from each
# agency's own start, never the corpus's.
_FIRST_OBSERVED_GRACE_DAYS = 2


def _first_observed(
    members: list[str],
    first_seen: dict[str, dict[str, str]],
    key: str,
    tracked: dict[str, str],
) -> dict | None:
    """First-observed provenance for one cluster: who carried the passage earliest.

    Returns the per-member first-seen dates (oldest first), the single earliest
    agency, and a tier describing how much weight the ordering bears:

    - ``added``: the earliest agency first showed the passage well after it was
      itself first tracked, so we watched it enter — the strongest signal.
    - ``present-at-start``: the earliest agency already had it when we began
      tracking that agency; others adopted it later, but its own origin may
      predate the corpus.
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
        winners[0] in tracked
        and (earliest - datetime.fromisoformat(tracked[winners[0]])).days
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
    first_seen: FirstSeen | None = None,
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
                    _first_observed(members, first_seen.keys, key, first_seen.tracked)
                    if first_seen is not None
                    else None
                ),
                "mergeMethod": "exact",
            }
        )

    # Canonical-phrase clusters: agencies whose text contains a template phrase,
    # however it is worded. The shared text is the phrase itself — showing a
    # host sentence would claim more than the match supports.
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
                "canonicalText": phrase,
                "kind": "phrase",
                "memberAbbrs": members,
                "count": len(members),
                "alsoInDta": dta_abbr in members,
                "containsCanonicalPhrase": True,
                "firstObserved": (
                    _first_observed(
                        members, first_seen.phrases, phrase_id, first_seen.tracked
                    )
                    if first_seen is not None
                    else None
                ),
                "mergeMethod": "phrase",
            }
        )

    clusters.sort(key=lambda c: (-c["count"], c["normKey"]))
    return clusters, shared_count


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
    profile_model: str | None = None,
    currency: dict | None = None,
    latest_capture_suspect: bool = False,
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
        "profileModel": profile_model,
        "standard": (
            standard_report(profile, (currency or {}).get("statedLastUpdated"))
            if profile
            else None
        ),
        "currency": currency,
        # The newest capture failed (quarantined), so `body` is the last good
        # revision rather than what the scraper holds today.
        "latestCaptureSuspect": latest_capture_suspect,
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
    classes: dict[str, dict[str, Classification]] | None = None,
) -> list[dict]:
    """Index of every agency with coverage status + revision summary, sorted by abbr.

    `revisionCount` counts every capture that differed; `changeCount` only the
    revisions whose substance changed. The site headlines the latter.
    """
    currencies = currencies or {}
    classes = classes or {}
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
                "changeCount": content_change_count(revs, classes.get(abbr, {})),
                "originality": originalities[abbr]["score"] if has_statement else None,
                "currency": currencies.get(abbr),
            }
        )
    return sorted(index, key=lambda a: a["abbr"])


def content_change_count(
    revs: list[Revision], classes: dict[str, Classification]
) -> int:
    """Revisions classified as a change of substance (an unclassified pair counts)."""
    return sum(
        1
        for rev in revs
        if (c := classes.get(rev.sha)) is not None
        and (c.is_content or c.kind == UNCLASSIFIED)
    )


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
                    **_change_fields(i, rev, classes.get(abbr, {})),
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
    captures = load_captures()
    logger.info("Loaded %d agencies, %d statements", len(agencies), len(statements))

    logger.info("Walking git history for %d statements...", len(statements))
    bulk = bulk_import_shas()
    timelines: dict[str, list[Revision]] = {}
    suspect: dict[str, bool] = {}
    for abbr in statements:
        revs, newest_dropped = quarantine_revisions(
            abbr, git_file_revisions(abbr, bulk), captures
        )
        timelines[abbr] = collapse_reverts(revs)
        suspect[abbr] = newest_dropped
        if newest_dropped:
            # Show the last good capture as the statement, not the failed one.
            statements[abbr]["body"] = timelines[abbr][-1].body
    total_revisions = sum(len(r) for r in timelines.values())

    names = {
        abbr: d["frontmatter"].get("agency", abbr) for abbr, d in statements.items()
    }
    logger.info("Classifying revision changes...")
    classes = classify_timelines(timelines, names)
    timeline = build_timeline(timelines, agencies, statements, classes)

    first_seen = first_seen_passages(timelines)
    corpus_start = first_seen.corpus_start

    passages_by_abbr = {
        abbr: segment_passages(data["body"], abbr) for abbr, data in statements.items()
    }
    clusters, shared_count = build_clusters(passages_by_abbr, first_seen=first_seen)
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
    readings = profile_timelines(timelines, classes, names)
    profiles = {abbr: [r.profile for r in rs] for abbr, rs in readings.items()}
    profile_models = {
        abbr: next((r.model for r in reversed(rs) if r.profile is not None), None)
        for abbr, rs in readings.items()
    }
    currencies = {}
    for abbr, revs in timelines.items():
        content_dates = [
            rev.date
            for rev in revs
            if (c := classes.get(abbr, {}).get(rev.sha)) is not None and c.is_content
        ]
        currencies[abbr] = staleness(
            profiles[abbr][-1] if profiles[abbr] else None,
            statements[abbr]["frontmatter"].get("last_updated_text"),
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
        agencies, statements, timelines, originalities, currencies, classes
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
            profile_models[abbr],
            currencies[abbr],
            suspect[abbr],
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
            "changes": sum(a["changeCount"] for a in agency_index),
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
