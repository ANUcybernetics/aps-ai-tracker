"""Unit tests for the JSON exporter's pure functions.

These cover the tricky, behaviour-bearing logic — passage normalisation, the
revert/no-net-change collapse, originality scoring and clustering — without
touching git or a model.
"""

import pytest

from aps_ai_tracker.export import (
    Passage,
    Revision,
    build_clusters,
    collapse_reverts,
    is_noise_revision,
    normalise_passage,
    originality_score,
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


def _body_rev(body: str, subject: str = "update") -> Revision:
    return Revision(
        sha="s",
        date="2026-01-01T00:00:00+00:00",
        subject=subject,
        message="",
        body=body,
        body_key=body,
        bulk=False,
    )


def test_noise_revision_detects_destination_only_link_change():
    before = _body_rev(
        "[DPS AI statement](https://www.aph.gov.au/-/media/statement.pdf)"
    )
    after = _body_rev(
        "[DPS AI statement](https://static.aph.gov.au/-/media/statement.pdf?rev=2)"
    )
    assert is_noise_revision(after, before)


def test_noise_revision_handles_parentheses_in_link_destinations():
    before = _body_rev("Download [here](https://example.gov.au/file%20(old).pdf).")
    after = _body_rev("Download [here](https://example.gov.au/file%20(new).pdf).")
    assert is_noise_revision(after, before)


def test_noise_revision_detects_standalone_link_churn():
    before = _body_rev("## Contact\n\nEmail the accountable official.")
    after = _body_rev(
        "## Contact\n\nEmail the accountable official.\n\n"
        "[January–June 2026](https://example.gov.au/register.pdf)"
    )
    assert is_noise_revision(after, before)


def test_noise_revision_preserves_changed_link_label():
    before = _body_rev("See the [2025 policy](https://example.gov.au/policy).")
    after = _body_rev("See the [2026 policy](https://example.gov.au/policy).")
    assert not is_noise_revision(after, before)


def test_noise_revision_does_not_mask_prose_change_alongside_url_churn():
    before = _body_rev(
        "We are trialling AI. Read the [policy](https://example.gov.au/old)."
    )
    after = _body_rev(
        "We are deploying AI. Read the [policy](https://example.gov.au/new)."
    )
    assert not is_noise_revision(after, before)


def test_noise_revision_preserves_commit_message_annotations():
    assert is_noise_revision(_body_rev("Changed body", "strip nav-chrome"))


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
