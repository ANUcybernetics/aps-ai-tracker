"""Unit tests for the JSON exporter's pure functions.

These cover the tricky, behaviour-bearing logic — passage normalisation, the
revert/no-net-change collapse, originality scoring, clustering and similarity —
without touching git or the OpenAI API.
"""

import pytest

from aps_ai_transparency_tracker.export import (
    Passage,
    Revision,
    build_clusters,
    collapse_reverts,
    content_hash,
    cosine_neighbours,
    load_embedding_cache,
    normalise_passage,
    originality_score,
    save_embedding_cache,
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
    ("url", "has", "expected"),
    [
        ("http://x", True, "published"),
        (None, False, "exempt"),
        ("http://x", False, "not-yet"),
    ],
)
def test_statement_status(url, has, expected):
    assert statement_status(url, has) == expected


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
    clusters, shared_count = build_clusters(by_abbr)
    exact = [c for c in clusters if c["mergeMethod"] == "exact"]
    phrase = [c for c in clusters if c["mergeMethod"] == "phrase"]
    # The identical sentence is shared by A and B.
    assert any(c["count"] == 2 and set(c["memberAbbrs"]) == {"A", "B"} for c in exact)
    # The accountable-official phrase clusters A and DTA, flagged as in DTA.
    acc = next(c for c in phrase if c["normKey"] == "phrase:accountable-official")
    assert acc["alsoInDta"] is True
    assert set(acc["memberAbbrs"]) == {"A", "DTA"}


# --- embeddings cache + similarity -----------------------------------------


def test_content_hash_is_stable_and_prefixed():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc").startswith("sha256:")
    assert content_hash("abc") != content_hash("abd")


def test_embedding_cache_roundtrip(tmp_path):
    path = tmp_path / "embeddings.json"
    cache = {"sha256:b": {"model": "m", "dim": 2, "vector": [0.1, 0.2]}, "sha256:a": {}}
    save_embedding_cache(path, cache)
    assert load_embedding_cache(path) == cache


def test_cosine_neighbours_ranks_and_builds_knn_edges():
    pytest.importorskip("numpy")
    vectors = {"A": [1.0, 0.0], "B": [0.0, 1.0], "C": [1.0, 0.05]}
    neighbours, edges = cosine_neighbours(vectors, k=1)
    assert neighbours["A"][0]["abbr"] == "C"  # A is closest to C, not B
    assert any({e["a"], e["b"]} == {"A", "C"} for e in edges)  # nearest-neighbour edge
    assert all(e["a"] < e["b"] for e in edges)  # deduped, ordered
