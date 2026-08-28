"""Unit tests for the JSON exporter's pure functions.

These cover the tricky, behaviour-bearing logic — passage normalisation, the
revert/no-net-change collapse, originality scoring and clustering — without
touching git or a model.
"""

import pytest

from aps_ai_tracker.changes import Classification
from aps_ai_tracker.export import (
    Captures,
    FirstSeen,
    Passage,
    Revision,
    annotated_noise,
    build_clusters,
    classify_timelines,
    collapse_reverts,
    normalise_passage,
    originality_score,
    quarantine_revisions,
    segment_passages,
    source_type,
    statement_status,
)

# --- normalise_passage ------------------------------------------------------


def test_normalise_strips_links_markup_and_case():
    raw = "The [Policy](https://x.gov.au/p) for **Responsible** use of AI."
    assert normalise_passage(raw) == "the policy for responsible use of ai"


def test_normalise_strips_nav_cruft_and_list_marker():
    assert normalise_passage("- Back to top of the page") == ""
    assert "opens in a new tab" not in normalise_passage(
        "See more (Opens in a new tab/window)"
    )


def test_normalise_collapses_whitespace_and_punctuation():
    assert normalise_passage("AI-related   work,  done.") == "ai related work done"


# --- segment_passages -------------------------------------------------------


def test_segment_splits_kinds_and_drops_stubs():
    body = (
        "# A heading that is long enough to keep\n\n"
        "An ordinary paragraph with several words in it.\n\n"
        "- first list item with enough words here\n"
        "- second list item with enough words here\n\n"
        "On\n\n"  # too short -> dropped
    )
    passages = segment_passages(body, "X")
    kinds = [p.kind for p in passages]
    assert kinds == ["heading", "paragraph", "list_item", "list_item"]
    assert all(len(p.normalised) >= 25 for p in passages)


# --- collapse_reverts -------------------------------------------------------


def _rev(key: str, sha: str = "s", bulk: bool = False) -> Revision:
    return Revision(
        sha=sha,
        date="2026-01-01T00:00:00+00:00",
        subject="x",
        message="",
        body=key,
        body_key=key,
        bulk=bulk,
    )


def _body_rev(body: str, subject: str = "update", sha: str = "s") -> Revision:
    return Revision(
        sha=sha,
        date="2026-01-01T00:00:00+00:00",
        subject=subject,
        message="",
        body=body,
        body_key=body,
        bulk=False,
    )


def test_annotated_noise_reads_commit_message():
    assert annotated_noise(_body_rev("Changed body", "strip nav-chrome"))
    assert not annotated_noise(_body_rev("Changed body", "update 3 statements"))


def test_annotation_outranks_model_classification(monkeypatch):
    # The model called the diff substantive, but the commit says it was our
    # own cleanup: the annotation wins so the change is never shown as the
    # agency's.
    monkeypatch.setattr(
        "aps_ai_tracker.export.classify_pairs",
        lambda pairs: {
            pid: Classification(kind="substantive", method="llm", summary="Drops X")
            for pid in pairs
        },
    )
    revs = [
        _body_rev("A long statement.", sha="a1"),
        _body_rev(
            "A statement.", "statements: strip nav-chrome across the corpus", "b2"
        ),
    ]
    classes = classify_timelines({"X": revs}, {"X": "Agency X"})
    assert classes["X"]["b2"].kind == "scrape-noise"
    assert classes["X"]["b2"].method == "rule"
    assert classes["X"]["b2"].summary == "Drops X"


# --- quarantine_revisions ---------------------------------------------------


def test_quarantine_drops_listed_revision():
    revs = [_body_rev("full " * 100, sha="aaa1"), _body_rev("intro", sha="bbb2")]
    kept, newest_dropped = quarantine_revisions(
        "X", revs, Captures(quarantine=(("X", "bbb"),))
    )
    assert [r.sha for r in kept] == ["aaa1"]
    assert newest_dropped


def test_quarantine_drops_unconfirmed_large_shrink():
    revs = [
        _body_rev("full " * 100, sha="aaa1"),
        _body_rev("intro only", sha="bbb2"),
        _body_rev("full " * 101, sha="ccc3"),
    ]
    kept, newest_dropped = quarantine_revisions("X", revs, Captures())
    assert [r.sha for r in kept] == ["aaa1", "ccc3"]
    assert not newest_dropped


def test_quarantine_keeps_confirmed_shrink():
    revs = [_body_rev("full " * 100, sha="aaa1"), _body_rev("short now", sha="bbb2")]
    kept, newest_dropped = quarantine_revisions(
        "X", revs, Captures(confirmed=(("X", "bbb2"),))
    )
    assert [r.sha for r in kept] == ["aaa1", "bbb2"]
    assert not newest_dropped


def test_quarantine_only_matches_the_named_agency():
    revs = [_body_rev("full " * 100, sha="aaa1"), _body_rev("full " * 99, sha="bbb2")]
    kept, _ = quarantine_revisions("X", revs, Captures(quarantine=(("Y", "bbb2"),)))
    assert len(kept) == 2


def test_collapse_drops_revert_excursion():
    # good -> spurious -> revert (back to good) collapses to a single state.
    revs = [_rev("A"), _rev("B"), _rev("A")]
    assert [r.body_key for r in collapse_reverts(revs)] == ["A"]


def test_collapse_drops_consecutive_no_change():
    revs = [_rev("A"), _rev("A"), _rev("B")]
    assert [r.body_key for r in collapse_reverts(revs)] == ["A", "B"]


def test_collapse_preserves_genuine_changes():
    revs = [_rev("A"), _rev("B"), _rev("C")]
    assert [r.body_key for r in collapse_reverts(revs)] == ["A", "B", "C"]


def test_collapse_drops_only_the_excursion():
    revs = [_rev("A"), _rev("B"), _rev("A"), _rev("C")]
    assert [r.body_key for r in collapse_reverts(revs)] == ["A", "C"]


# --- originality_score ------------------------------------------------------


def _passage(normalised: str, key: str, abbr: str = "X") -> Passage:
    return Passage(abbr, normalised, normalised, key, "paragraph")


def test_originality_all_unique_is_one():
    passages = [_passage("a" * 30, "k1"), _passage("b" * 30, "k2")]
    assert originality_score(passages, {"k1": 1, "k2": 1})["score"] == 1.0


def test_originality_is_length_weighted():
    passages = [_passage("a" * 30, "k1"), _passage("b" * 10, "k2")]
    # k1 shared by 3 agencies -> 30 of 40 chars are boilerplate.
    result = originality_score(passages, {"k1": 3, "k2": 1})
    assert result["score"] == 0.25
    assert result["sharedChars"] == 30
    assert result["shared"] == 1


def test_originality_canonical_phrase_counts_as_shared():
    passages = [_passage("we appoint an accountable official here", "k1")]
    assert originality_score(passages, {"k1": 1})["score"] == 0.0


# --- statement_status / source_type ----------------------------------------


@pytest.mark.parametrize(
    ("scope", "url", "has", "expected"),
    [
        ("mandatory", "http://x", True, "published"),
        ("exempt", None, True, "published"),
        # obligated but nothing published: a genuine gap, not an exemption
        ("mandatory", None, False, "not-yet"),
        # outside the mandate and silent
        ("voluntary", None, False, "exempt"),
        ("exempt", None, False, "exempt"),
        # we know of a statement but failed to capture it this run
        ("mandatory", "http://x", False, "not-yet"),
        ("voluntary", "http://x", False, "not-yet"),
    ],
)
def test_statement_status(scope, url, has, expected):
    assert statement_status(scope, url, has) == expected


def test_source_type_detects_pdf():
    assert source_type({"raw_hash": "abc"}) == "pdf"
    assert source_type({}) == "html"


# --- build_clusters ---------------------------------------------------------


def test_build_clusters_finds_exact_and_phrase_reuse():
    shared = "we comply with all applicable legislation and policy"
    by_abbr = {
        "A": segment_passages(f"{shared}\n\nWe appoint an accountable official.", "A"),
        "B": segment_passages(
            f"{shared}\n\nBespoke text unique to agency B here.", "B"
        ),
        "DTA": segment_passages("We appoint an accountable official always.", "DTA"),
    }
    clusters, _shared_count = build_clusters(by_abbr)
    exact = [c for c in clusters if c["mergeMethod"] == "exact"]
    phrase = [c for c in clusters if c["mergeMethod"] == "phrase"]
    # The identical sentence is shared by A and B.
    assert any(c["count"] == 2 and set(c["memberAbbrs"]) == {"A", "B"} for c in exact)
    # The accountable-official phrase clusters A and DTA, flagged as in DTA.
    acc = next(c for c in phrase if c["normKey"] == "phrase:accountable-official")
    assert acc["alsoInDta"] is True
    assert set(acc["memberAbbrs"]) == {"A", "DTA"}
    # The shared text is the phrase, never a host sentence from one agency.
    assert acc["canonicalText"] == "accountable official"


def test_first_observed_grace_is_measured_from_each_agencys_own_start():
    shared = "we comply with all applicable legislation and policy"
    by_abbr = {
        "A": segment_passages(shared, "A"),
        "B": segment_passages(shared, "B"),
    }
    key = by_abbr["A"][0].norm_key
    # A carried the passage from its first tracked day; B joined the corpus
    # months later and also carried it from day one. Nobody watched it enter.
    first_seen = FirstSeen(
        keys={
            "A": {key: "2026-06-07T00:00:00+10:00"},
            "B": {key: "2026-06-07T00:00:00+10:00"},
        },
        phrases={"A": {}, "B": {}},
        tracked={"A": "2026-06-07T00:00:00+10:00", "B": "2026-06-07T00:00:00+10:00"},
    )
    clusters, _ = build_clusters(by_abbr, first_seen=first_seen)
    assert clusters[0]["firstObserved"]["tier"] == "tied"

    first_seen = FirstSeen(
        keys={
            "A": {key: "2026-06-07T00:00:00+10:00"},
            "B": {key: "2026-07-07T00:00:00+10:00"},
        },
        phrases={"A": {}, "B": {}},
        tracked={"A": "2026-06-07T00:00:00+10:00", "B": "2025-11-11T00:00:00+11:00"},
    )
    clusters, _ = build_clusters(by_abbr, first_seen=first_seen)
    observed = clusters[0]["firstObserved"]
    assert observed["abbr"] == "A"
    # A had it on its own first day, long after the corpus opened: still only
    # "present at start" for A, not something we watched it add.
    assert observed["tier"] == "present-at-start"
    assert first_seen.corpus_start == "2025-11-11T00:00:00+11:00"
