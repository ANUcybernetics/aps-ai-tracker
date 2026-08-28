"""Corpus-level views derived from per-revision profiles.

- adoption series: for each policy concept, how many tracked statements carry
  it at the end of each month, and every agency-level transition (a concept
  appearing in or disappearing from a statement) with its date and revision
- staleness: what each statement says about its own currency, against the
  policy's annual-review rule and the 15 December 2025 start of version 2.0
"""

import re
from datetime import UTC, datetime, timedelta

from .profiles import (
    CONCEPTS,
    POLICY_V2_EFFECTIVE,
    POLICY_V2_MILESTONES,
    Profile,
    concept_flags,
)

ANNUAL_REVIEW_DAYS = 365
_STATED_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _stated_stamp(stated: str | None) -> str | None:
    """A model-extracted date as YYYY-MM-DD, or None when absent or malformed.

    A month-only date counts from the end of that month, giving the agency the
    benefit of the doubt in both the v2.0 and annual-review comparisons.
    """
    if not stated or not _STATED_DATE_RE.match(stated):
        return None
    return stated if len(stated) == 10 else f"{stated}-28"


def _month(date: str) -> str:
    return date[:7]


def _months_between(start: str, end: str) -> list[str]:
    """Inclusive list of YYYY-MM from start's month to end's month."""
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def build_adoption(
    profiled: dict[str, list[tuple[str, str, bool, Profile | None]]],
    corpus_start: str,
    built_at: str,
) -> dict:
    """Monthly concept adoption plus per-agency transitions.

    `profiled` maps abbr → chronological (date, sha, is_noise, profile) rows; a
    None profile (no extraction available) leaves that statement out of the
    denominators for the months it covers.
    """
    months = _months_between(corpus_start, built_at)
    series: dict[str, list[int]] = {cid: [0] * len(months) for cid, _ in CONCEPTS}
    tracked = [0] * len(months)
    transitions: list[dict] = []

    for abbr, rows in sorted(profiled.items()):
        # State of this statement at each month end: the latest row on or
        # before the month.
        for mi, month in enumerate(months):
            state = None
            for date, _sha, _noise, profile in rows:
                if _month(date) <= month:
                    state = profile
            if state is None:
                continue
            tracked[mi] += 1
            for cid, on in concept_flags(state).items():
                if on:
                    series[cid][mi] += 1
        # Transitions between consecutive readable revisions.
        prev: Profile | None = None
        for date, sha, noise, profile in rows:
            if profile is None or noise:
                continue
            if prev is not None:
                before, after = concept_flags(prev), concept_flags(profile)
                for cid, _label in CONCEPTS:
                    if before[cid] != after[cid]:
                        transitions.append(
                            {
                                "concept": cid,
                                "abbr": abbr,
                                "date": date,
                                "sha": sha,
                                "direction": "added" if after[cid] else "removed",
                            }
                        )
            prev = profile

    transitions.sort(key=lambda t: (t["date"], t["abbr"], t["concept"]))
    return {
        "months": months,
        "tracked": tracked,
        "concepts": [
            {"id": cid, "label": label, "counts": series[cid]}
            for cid, label in CONCEPTS
        ],
        "transitions": transitions,
        "milestones": POLICY_V2_MILESTONES,
    }


def staleness(
    profile: Profile | None,
    last_content_change: str | None,
    first_seen: str,
    built_at: str,
) -> dict:
    """What we can say about a statement's currency.

    `updatedSincePolicyV2` is true when either the statement's own last-updated
    date or an observed content change falls on or after 15 December 2025.
    `annualReviewOverdue` uses the statement's own date only: the Standard
    requires review at least yearly, and a self-declared date more than a year
    old is the agency's own admission. Null when no date is stated.
    """
    stated = profile.last_updated_stated if profile else None
    stamp = _stated_stamp(stated)
    observed = last_content_change[:10] if last_content_change else None
    since_v2 = any(
        d is not None and d >= POLICY_V2_EFFECTIVE for d in (stamp, observed)
    )
    overdue: bool | None = None
    if stamp:
        cutoff = datetime.fromisoformat(built_at) - timedelta(days=ANNUAL_REVIEW_DAYS)
        overdue = datetime.fromisoformat(stamp).replace(tzinfo=UTC) < cutoff
    return {
        "statedLastUpdated": stated,
        "statedFirstPublished": profile.first_published_stated if profile else None,
        "lastContentChange": last_content_change,
        "firstSeen": first_seen,
        "updatedSincePolicyV2": since_v2,
        "annualReviewOverdue": overdue,
    }
