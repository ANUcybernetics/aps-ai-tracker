"""Read each statement revision into a fixed-vocabulary profile of what it claims.

The DTA's Standard for AI transparency statements lists what a statement must
contain (intentions, usage classification, public-facing use, monitoring
measures, policy and legislative compliance, a last-updated date, a contact),
and version 2.0 of the policy (effective 15 December 2025) adds agency-level
obligations that statements have started to report on: a Chief AI Officer, a
strategic position on AI, an internal use-case register, mandatory staff
training. A profile records, per revision, which of those the statement
addresses and what it commits to, using closed vocabularies so profiles compare
cleanly across agencies and across time.

Diffing two profiles gives the structured, interpretable version of "what
changed": a commitment dropped, an officer appointed, a use disclosed. A bullet
expanded into a paragraph about the same thing produces no delta at all.

Extraction is one Claude call per readable revision, anchored on the previous
revision's profile so that unchanged fields (and the wording of unchanged
commitments) carry over verbatim and only genuine changes show up as deltas.
Results are cached by (body hash, previous-profile hash).
"""

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from . import llm
from .scraper import logger

SCHEMA_VERSION = 2
CACHE_PATH = llm.CACHE_DIR / "profiles.json"

# The policy's own dates, used for the staleness and adoption views.
POLICY_V2_EFFECTIVE = "2025-12-15"
POLICY_V2_MILESTONES = [
    {
        "date": "2025-02-28",
        "label": "Transparency statements first required (policy v1.1)",
    },
    {"date": "2025-12-15", "label": "Policy v2.0 takes effect"},
    {"date": "2026-06-15", "label": "Strategic position on AI due (6 months)"},
    {
        "date": "2026-12-15",
        "label": "Use-case register, mandatory training and use-case owners due (12 months)",
    },
]

UsagePattern = Literal[
    "decision-making-and-administrative-action",
    "analytics-for-insights",
    "workplace-productivity",
    "image-processing",
]
Domain = Literal[
    "service-delivery",
    "compliance-and-fraud-detection",
    "law-enforcement-intelligence-and-security",
    "policy-and-legal",
    "scientific",
    "corporate-and-enabling",
]
Presence = Literal["not-mentioned", "planned", "in-place"]
Measure = Literal[
    "risk-assessment",
    "human-review-of-outputs",
    "audit-or-assurance",
    "staff-training",
    "use-case-register",
    "incident-or-concern-reporting",
    "testing-or-evaluation",
    "privacy-or-security-controls",
    "governance-body",
    "acceptable-use-policy",
]


class Commitment(BaseModel):
    """One explicit promise or self-imposed limit the statement makes."""

    text: str = Field(
        description="Short paraphrase, at most 20 words, in the agency's terms"
    )
    kind: Literal["will-not", "will", "human-oversight"]


class Profile(BaseModel):
    """What one revision of a statement says, in closed vocabularies."""

    summary: str = Field(
        description="One or two plain sentences: what the agency says it uses AI for and how it governs that"
    )
    intentions_stated: bool = Field(
        description="Explains why the agency uses or is considering AI"
    )
    usage_patterns: list[UsagePattern] = Field(
        description="DTA usage patterns the statement says are in use (not merely defined or ruled out)"
    )
    domains: list[Domain] = Field(
        description="DTA domains the statement says are in use (not merely defined or ruled out)"
    )
    public_facing: Literal[
        "not-addressed", "none", "with-human-review", "without-human-review", "unclear"
    ] = Field(
        description="Whether AI is used where the public directly interacts with it or is significantly affected by its outputs"
    )
    public_interaction_commitment: bool = Field(
        description="Explicitly commits not to use AI in public-facing or public-impacting ways without a human intermediary or review"
    )
    monitoring_measures_stated: bool = Field(
        description="Describes measures to monitor effectiveness or protect against negative impacts"
    )
    measures: list[Measure]
    accountable_official: Literal["not-mentioned", "designated"]
    accountable_official_role: str | None = Field(
        description="Job title of the accountable official, if given (never a person's name)"
    )
    chief_ai_officer: Presence
    chief_ai_officer_role: str | None = Field(
        description="Job title holding or slated for the Chief AI Officer role, if given (never a name)"
    )
    use_case_register: Presence
    staff_training: Literal["not-mentioned", "available", "mandatory"]
    strategic_position: Presence = Field(
        description="An AI strategy, roadmap or strategic position on AI adoption"
    )
    review_cadence: Literal[
        "not-stated", "annual", "on-change", "annual-and-on-change", "other"
    ]
    first_published_stated: str | None = Field(
        description="Date the statement says it was first published, as YYYY-MM-DD or YYYY-MM"
    )
    last_updated_stated: str | None = Field(
        description="Date the statement says it was last updated or reviewed, as YYYY-MM-DD or YYYY-MM"
    )
    contact_provided: bool
    named_tools: list[str] = Field(
        description="AI products named as in use, as canonical product names (e.g. 'Microsoft 365 Copilot', 'ChatGPT')"
    )
    policy_version: Literal["not-referenced", "v1", "v2", "unspecified"] = Field(
        description="Which version of the Policy for the responsible use of AI in government the statement refers to"
    )
    policy_compliance_stated: bool = Field(
        description="States that the agency complies with or implements the policy"
    )
    legislation_compliance_stated: bool = Field(
        description="States compliance with applicable legislation (Privacy Act, Archives Act, PGPA Act, etc.)"
    )
    commitments: list[Commitment] = Field(
        description="Explicit promises and self-imposed limits, especially 'we will not…' statements"
    )


SYSTEM_PROMPT = """\
You read Australian Government AI transparency statements and fill in a
structured profile of what each one says.

Context. Under the Digital Transformation Agency's Policy for the responsible
use of AI in government, every Commonwealth agency must publish a statement of
its approach to AI. The DTA's Standard for AI transparency statements says a
statement must, at minimum, give: the intentions behind the agency's use of AI;
a classification of that use by the DTA's usage patterns (decision making and
administrative action; analytics for insights; workplace productivity; image
processing) and domains (service delivery; compliance and fraud detection; law
enforcement, intelligence and security; policy and legal; scientific; corporate
and enabling); whether the public may directly interact with, or be
significantly impacted by, AI without human review; measures to monitor
effectiveness and protect the public from negative impacts; compliance with the
policy and with legislation; and when the statement was last updated. It must
also give a contact. Version 2.0 of the policy (effective 15 December 2025) adds
a Chief AI Officer, a strategic position on AI, an internal AI use-case register
and mandatory staff training, and statements increasingly report on these.

Rules:
- Record only what the statement itself says. Do not infer from what is typical.
- usage_patterns and domains: include a pattern or domain only when the agency
  says it uses (or is trialling) AI that way. A statement that merely quotes the
  DTA definitions, or lists a pattern as "not used", does not count.
- public_facing: "none" when the agency says it does not use AI where the
  public interacts with or is significantly impacted by it; "with-human-review"
  when it does so only with a human intermediary or review; "without-human-review"
  when it discloses such use without that safeguard; "not-addressed" when the
  statement is silent; "unclear" otherwise.
- public_interaction_commitment is true only for an explicit promise (e.g. "we
  do not propose to use AI where the public may directly interact with or be
  significantly impacted by it without a human intermediary"). A bare statement
  of current fact ("we currently have no public-facing AI") is public_facing
  "none" but not a commitment.
- chief_ai_officer / use_case_register / strategic_position: "in-place" when
  the statement says it exists or has been appointed; "planned" when it is
  being established, will be appointed by a date, or is under development.
- staff_training: "mandatory" only when training is required (before access,
  for all staff, annually, etc.); "available" when merely offered.
- review_cadence: "annual" for yearly review; "on-change" for review when the
  approach changes; "annual-and-on-change" when both; "other" for any other
  stated cadence.
- Dates: give YYYY-MM-DD when the day is stated, YYYY-MM when only the month is.
  Do not derive a date from a version number or from page chrome.
- Roles, never names: record job titles only.
- commitments: paraphrase each explicit promise or self-imposed limit in at most
  20 words, keeping the agency's own key terms so the same commitment reads the
  same across revisions. Every "we will not / do not / must not use AI to…"
  belongs here with kind "will-not"; promises of human oversight of AI outputs
  or decisions are "human-oversight"; other promises ("we will review annually",
  "we will publish a register") are "will". Do not include the intentions or
  generic values statements.
- summary: one or two plain sentences an educated reader could use to
  characterise the agency's stance, in Australian English.

When a previous revision's profile is supplied, the statement you are reading
is a later revision of the same agency's statement. Treat that profile as the
baseline: keep every field identical unless the new text says something
different on that field, and keep the previous wording of each commitment
verbatim wherever the statement still makes that commitment, even if the
agency has rephrased it. Add a commitment only when it is genuinely new; drop
one only when the statement no longer makes it. Rewording, reordering and
expansion are not changes.
"""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _chain_key(body: str, prev: Profile | None) -> str:
    """Cache key: the body plus the profile it was anchored on (if any)."""
    if prev is None:
        return _hash(body)
    anchor = _hash(json.dumps(prev.model_dump(mode="json"), sort_keys=True))
    return f"{_hash(body)}:{anchor}"


def _user_prompt(agency: str, body: str, prev: Profile | None) -> str:
    parts = [f"Agency: {agency}"]
    if prev is not None:
        parts.append(
            "Profile of the previous revision (baseline; keep unchanged fields and "
            "commitment wording verbatim):\n"
            + json.dumps(prev.model_dump(mode="json"), ensure_ascii=False, indent=1)
        )
    parts.append(f"AI transparency statement (Markdown):\n\n{body}")
    return "\n\n".join(parts)


@dataclass(frozen=True, slots=True)
class Step:
    """One revision in a statement's chain: its body and whether to read it.

    Noise revisions (nothing the agency wrote changed) are not read; they
    inherit the previous profile, so a rotating sidebar never costs a call.
    """

    body: str
    readable: bool


def _walk_chain(
    agency: str,
    steps: list[Step],
    cache: dict,
    live: set[str],
    lock: threading.Lock,
    can_call: bool,
) -> list[Profile | None]:
    """Profiles for one statement's revisions, oldest first, anchored in sequence."""
    out: list[Profile | None] = []
    prev: Profile | None = None
    for step in steps:
        if not step.readable and prev is not None:
            out.append(prev)
            continue
        key = _chain_key(step.body, prev)
        with lock:
            live.add(key)
            entry = cache.get(key)
        profile: Profile | None = None
        if entry and entry.get("v") == SCHEMA_VERSION:
            profile = Profile.model_validate(entry["profile"])
        elif can_call:
            try:
                profile = llm.extract(
                    SYSTEM_PROMPT, _user_prompt(agency, step.body, prev), Profile
                )
            except Exception as exc:  # noqa: BLE001 - logged, retried next run
                logger.warning("Profile extraction failed for %s: %s", agency, exc)
            if profile is not None:
                with lock:
                    cache[key] = {
                        "v": SCHEMA_VERSION,
                        "model": llm.MODEL,
                        "profile": profile.model_dump(mode="json"),
                    }
        out.append(profile)
        # A missing profile breaks the anchor; the next readable revision is
        # read unanchored rather than against a stale baseline.
        prev = profile
    return out


def extract_profiles(
    chains: dict[str, tuple[str, list[Step]]],
) -> dict[str, list[Profile | None]]:
    """Profiles per revision for {abbr: (agency, steps)}; chains run in parallel.

    Within a statement extraction is sequential (each revision is anchored on
    the last); across statements it is concurrent. Cached entries never cost a
    call; without a backend, uncached revisions come back None.
    """
    cache = llm.load_cache(CACHE_PATH)
    on_disk = dict(cache)
    live: set[str] = set()
    lock = threading.Lock()
    can_call = llm.api_available()
    if not can_call:
        logger.warning("No Claude backend available; uncached revisions get no profile")

    def run(
        item: tuple[str, tuple[str, list[Step]]],
    ) -> tuple[str, list[Profile | None]]:
        abbr, (agency, steps) = item
        return abbr, _walk_chain(agency, steps, cache, live, lock, can_call)

    results: dict[str, list[Profile | None]] = {}
    with ThreadPoolExecutor(max_workers=llm.WORKERS) as pool:
        for abbr, profiles in pool.map(run, sorted(chains.items())):
            results[abbr] = profiles
    extracted = sum(1 for k in live if k in cache and k not in on_disk)
    if extracted:
        logger.info("Extracted %d statement profiles via %s", extracted, llm.MODEL)

    pruned = {
        k: v for k, v in cache.items() if k in live and v.get("v") == SCHEMA_VERSION
    }
    if pruned != on_disk:
        llm.save_cache(CACHE_PATH, pruned)
    return results


# --- profile diffs ----------------------------------------------------------

Significance = Literal["minor", "notable", "significant"]


@dataclass(frozen=True, slots=True)
class Delta:
    field: str
    label: str  # human-readable description of the change
    direction: Literal["added", "removed", "changed"]
    significance: Significance
    before: str | None = None
    after: str | None = None


_LABELS = {
    "chief_ai_officer": "Chief AI Officer",
    "use_case_register": "AI use-case register",
    "strategic_position": "Strategic position on AI",
    "staff_training": "Staff training",
    "accountable_official": "Accountable official",
    "review_cadence": "Review cadence",
    "public_facing": "Public-facing AI use",
    "policy_version": "Policy version referenced",
    "usage_patterns": "Usage pattern",
    "domains": "Domain",
    "measures": "Safeguard",
    "named_tools": "Named tool",
    "commitments": "Commitment",
    "public_interaction_commitment": "Commitment: no public-facing AI without a human",
    "intentions_stated": "Intentions behind AI use",
    "monitoring_measures_stated": "Monitoring and protection measures",
    "contact_provided": "Public contact",
    "policy_compliance_stated": "Policy compliance statement",
    "legislation_compliance_stated": "Legislative compliance statement",
    "last_updated_stated": "Stated last-updated date",
    "first_published_stated": "Stated first-published date",
}

_PRESENCE_RANK = {"not-mentioned": 0, "planned": 1, "in-place": 2}
_TRAINING_RANK = {"not-mentioned": 0, "available": 1, "mandatory": 2}
# Fields whose ordered vocabulary lets a change read as progress or regression.
_ORDERED = {
    "chief_ai_officer": _PRESENCE_RANK,
    "use_case_register": _PRESENCE_RANK,
    "strategic_position": _PRESENCE_RANK,
    "staff_training": _TRAINING_RANK,
    "accountable_official": {"not-mentioned": 0, "designated": 1},
}
_BOOL_FIELDS = (
    "public_interaction_commitment",
    "intentions_stated",
    "monitoring_measures_stated",
    "contact_provided",
    "policy_compliance_stated",
    "legislation_compliance_stated",
)
_LIST_FIELDS = ("usage_patterns", "domains", "measures", "named_tools")
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "and",
        "or",
        "in",
        "on",
        "for",
        "with",
        "by",
        "is",
        "are",
        "be",
        "will",
        "not",
        "do",
        "does",
        "no",
        "we",
        "our",
        "its",
        "it",
        "that",
        "this",
        "as",
        "at",
        "from",
    ]
)


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP}


def _same_commitment(a: Commitment, b: Commitment) -> bool:
    """Fuzzy match: same kind and enough shared content words to be one promise."""
    if a.kind != b.kind:
        return False
    ta, tb = _tokens(a.text), _tokens(b.text)
    if not ta or not tb:
        return a.text.strip().lower() == b.text.strip().lower()
    return len(ta & tb) / len(ta | tb) >= 0.5


def _pretty(value: object) -> str:
    return str(value).replace("-", " ")


def diff_profiles(before: Profile, after: Profile) -> list[Delta]:
    """Field-level changes between two profiles, most significant first."""
    deltas: list[Delta] = []

    for name, rank in _ORDERED.items():
        b, a = getattr(before, name), getattr(after, name)
        if b == a:
            continue
        progressed = rank[a] > rank[b]
        significant = a == "in-place" or b == "in-place" or name in ("staff_training",)
        deltas.append(
            Delta(
                field=name,
                label=f"{_LABELS[name]}: {_pretty(b)} → {_pretty(a)}",
                direction="added" if progressed else "removed",
                significance="notable"
                if (progressed and significant)
                else ("significant" if not progressed else "minor"),
                before=b,
                after=a,
            )
        )

    for name in _BOOL_FIELDS:
        b, a = getattr(before, name), getattr(after, name)
        if b == a:
            continue
        weight: Significance = (
            "significant" if name == "public_interaction_commitment" else "notable"
        )
        deltas.append(
            Delta(
                field=name,
                label=f"{_LABELS[name]} {'added' if a else 'removed'}",
                direction="added" if a else "removed",
                significance=weight
                if not a or name == "public_interaction_commitment"
                else "minor",
                before=str(b),
                after=str(a),
            )
        )

    for name in ("public_facing", "review_cadence", "policy_version"):
        b, a = getattr(before, name), getattr(after, name)
        if b == a:
            continue
        weakened = name == "public_facing" and a in (
            "without-human-review",
            "not-addressed",
        )
        deltas.append(
            Delta(
                field=name,
                label=f"{_LABELS[name]}: {_pretty(b)} → {_pretty(a)}",
                direction="changed",
                significance="significant" if weakened else "notable",
                before=b,
                after=a,
            )
        )

    for name in _LIST_FIELDS:
        b, a = set(getattr(before, name)), set(getattr(after, name))
        for item in sorted(a - b):
            deltas.append(
                Delta(
                    name,
                    f"{_LABELS[name]} added: {_pretty(item)}",
                    "added",
                    "notable",
                    after=item,
                )
            )
        for item in sorted(b - a):
            # A disclosed use or a named tool disappearing is a change in what
            # the agency admits to; the safeguards list is a looser reading
            # and a dropped entry there is worth noting, not headlining.
            deltas.append(
                Delta(
                    name,
                    f"{_LABELS[name]} dropped: {_pretty(item)}",
                    "removed",
                    "notable" if name == "measures" else "significant",
                    before=item,
                )
            )

    matched: set[int] = set()
    for c in after.commitments:
        for i, old in enumerate(before.commitments):
            if i not in matched and _same_commitment(old, c):
                matched.add(i)
                break
        else:
            deltas.append(
                Delta(
                    "commitments",
                    f"New commitment ({_pretty(c.kind)}): {c.text}",
                    "added",
                    "notable",
                    after=c.text,
                )
            )
    for i, old in enumerate(before.commitments):
        if i not in matched:
            # A dropped limit ("will not") or oversight promise is the change
            # most worth noticing. A plain "will" is often time-bound ("a Chief
            # AI Officer will be appointed by July") and disappears when it is
            # fulfilled, so it is noted rather than headlined.
            deltas.append(
                Delta(
                    "commitments",
                    f"Commitment dropped ({_pretty(old.kind)}): {old.text}",
                    "removed",
                    "notable" if old.kind == "will" else "significant",
                    before=old.text,
                )
            )

    for name in ("last_updated_stated", "first_published_stated"):
        b, a = getattr(before, name), getattr(after, name)
        if b != a:
            deltas.append(
                Delta(
                    name,
                    f"{_LABELS[name]}: {b or '—'} → {a or '—'}",
                    "changed",
                    "minor",
                    b,
                    a,
                )
            )

    order = {"significant": 0, "notable": 1, "minor": 2}
    return sorted(
        deltas, key=lambda d: (order[d.significance], d.direction != "removed", d.label)
    )


def delta_dict(delta: Delta) -> dict:
    return {
        "field": delta.field,
        "label": delta.label,
        "direction": delta.direction,
        "significance": delta.significance,
        "before": delta.before,
        "after": delta.after,
    }


# --- report card against the Standard ---------------------------------------

STANDARD_ELEMENTS = [
    ("intentions", "Intentions behind AI use"),
    ("classification", "Use classified by DTA usage pattern or domain"),
    ("public-facing", "Public-facing use addressed"),
    ("monitoring", "Monitoring and protection measures"),
    ("policy-compliance", "Compliance with the policy"),
    ("legislation", "Compliance with legislation"),
    ("last-updated", "Date last updated"),
    ("contact", "Public contact"),
]


def standard_report(profile: Profile) -> dict[str, bool]:
    """Which of the Standard's minimum elements the profile shows as present."""
    return {
        "intentions": profile.intentions_stated,
        "classification": bool(profile.usage_patterns or profile.domains),
        "public-facing": profile.public_facing != "not-addressed",
        "monitoring": profile.monitoring_measures_stated,
        "policy-compliance": profile.policy_compliance_stated,
        "legislation": profile.legislation_compliance_stated,
        "last-updated": profile.last_updated_stated is not None,
        "contact": profile.contact_provided,
    }


# --- concept adoption -------------------------------------------------------

# The policy-tracking concepts charted over time: (id, label, predicate).
CONCEPTS: list[tuple[str, str]] = [
    ("chief-ai-officer", "Chief AI Officer in place"),
    ("chief-ai-officer-planned", "Chief AI Officer in place or planned"),
    ("accountable-official", "Accountable official designated"),
    ("use-case-register", "AI use-case register in place"),
    ("mandatory-training", "Mandatory staff training"),
    ("strategic-position", "Strategic position on AI (in place or planned)"),
    ("annual-review", "Commits to annual review"),
    ("public-interaction-commitment", "Commits to no public-facing AI without a human"),
    ("policy-v2", "References policy v2.0"),
    ("copilot", "Names Microsoft Copilot"),
    ("no-public-facing", "States no public-facing AI use"),
]


def concept_flags(profile: Profile) -> dict[str, bool]:
    tools = " ".join(profile.named_tools).lower()
    return {
        "chief-ai-officer": profile.chief_ai_officer == "in-place",
        "chief-ai-officer-planned": profile.chief_ai_officer != "not-mentioned",
        "accountable-official": profile.accountable_official == "designated",
        "use-case-register": profile.use_case_register == "in-place",
        "mandatory-training": profile.staff_training == "mandatory",
        "strategic-position": profile.strategic_position != "not-mentioned",
        "annual-review": profile.review_cadence in ("annual", "annual-and-on-change"),
        "public-interaction-commitment": profile.public_interaction_commitment,
        "policy-v2": profile.policy_version == "v2",
        "copilot": "copilot" in tools,
        "no-public-facing": profile.public_facing == "none",
    }
