"""Unit tests for the change classifier's deterministic rules and cache handling.

The Claude-backed path is exercised only through the cache: a stored assessment
is returned without an API call, and a missing one without a key comes back
`unclassified` so the exporter can fall back to its older heuristics.
"""

import pytest

from aps_ai_tracker import changes, llm
from aps_ai_tracker.changes import (
    UNCLASSIFIED,
    changed_lines,
    classify_pairs,
    rule_kind,
)

BODY = """# AI transparency statement

We use AI for workplace productivity.

- We will not use AI where the public may directly interact with it.
- Staff complete mandatory training.

Contact: [ai@agency.gov.au](mailto:ai@agency.gov.au)
"""


def test_formatting_only_change_is_noise():
    reflowed = BODY.replace("workplace productivity.", "workplace\nproductivity.")
    assert rule_kind(BODY, reflowed) == "formatting"
    assert rule_kind(BODY, BODY.replace("**", "").replace("# AI", "## AI")) == (
        "formatting"
    )


def test_link_destination_change_is_link_churn():
    retargeted = BODY.replace("mailto:ai@agency.gov.au", "mailto:ai@agency.gov.au?x=1")
    assert rule_kind(BODY, retargeted) == "link-churn"


def test_chrome_lines_are_noise():
    before = BODY + "\n![Media](https://x/a.jpg)\n\n### [Media](https://x/media)\n"
    after = BODY + "\n![Careers](https://x/b.jpg)\n\n### [Careers](https://x/careers)\n"
    assert rule_kind(before, after) == "chrome"


def test_relative_date_stamp_is_noise():
    before = BODY + "\nPage last reviewed: **2 days ago**\n"
    after = BODY + "\nPage last reviewed: **6 days ago**\n"
    assert rule_kind(before, after) == "date-stamp"


def test_reordered_passages_are_cosmetic():
    reordered = BODY.replace(
        "- We will not use AI where the public may directly interact with it.\n"
        "- Staff complete mandatory training.",
        "- Staff complete mandatory training.\n"
        "- We will not use AI where the public may directly interact with it.",
    )
    # Two list items inside one block: swapping them changes the block text, so
    # this is not a passage-level reorder…
    assert rule_kind(BODY, reordered) is None
    # …but moving a whole paragraph is.
    moved = BODY.replace("We use AI for workplace productivity.\n\n", "") + (
        "\nWe use AI for workplace productivity.\n"
    )
    assert rule_kind(BODY, moved) == "reordering"


def test_removed_commitment_needs_reading():
    dropped = BODY.replace(
        "- We will not use AI where the public may directly interact with it.\n", ""
    )
    assert rule_kind(BODY, dropped) is None
    assert changed_lines(BODY, dropped) == [
        "- We will not use AI where the public may directly interact with it."
    ]


def test_classify_pairs_uses_rules_cache_then_unclassified(tmp_path, monkeypatch):
    monkeypatch.setattr(changes, "CACHE_PATH", tmp_path / "changes.json")
    monkeypatch.setenv("APS_LLM_BACKEND", "api")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    dropped = BODY.replace("- Staff complete mandatory training.\n", "")
    added = BODY + "\nWe have appointed a Chief AI Officer.\n"
    llm.save_cache(
        changes.CACHE_PATH,
        {
            changes._pair_key(BODY, added): {
                "v": changes.SCHEMA_VERSION,
                "model": "test",
                "kind": "substantive",
                "summary": "Appoints a Chief AI Officer.",
                "noteworthy": ["Chief AI Officer appointed"],
            }
        },
    )
    result = classify_pairs(
        {
            "a": ("A", BODY, BODY.replace("# AI", "## AI")),
            "b": ("B", BODY, added),
            "c": ("C", BODY, dropped),
        }
    )
    assert (result["a"].kind, result["a"].method) == ("formatting", "rule")
    assert (result["b"].kind, result["b"].method) == ("substantive", "llm")
    assert result["b"].summary == "Appoints a Chief AI Officer."
    assert result["b"].noteworthy == ["Chief AI Officer appointed"]
    assert (result["c"].kind, result["c"].method) == (UNCLASSIFIED, "uncached")
    assert not result["c"].is_noise


def test_stale_schema_version_is_ignored_and_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(changes, "CACHE_PATH", tmp_path / "changes.json")
    monkeypatch.setenv("APS_LLM_BACKEND", "api")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    added = BODY + "\nNew paragraph of substance.\n"
    llm.save_cache(
        changes.CACHE_PATH,
        {
            changes._pair_key(BODY, added): {
                "v": changes.SCHEMA_VERSION - 1,
                "kind": "cosmetic",
                "summary": "old",
                "noteworthy": [],
            }
        },
    )
    result = classify_pairs({"x": ("X", BODY, added)})
    assert result["x"].kind == UNCLASSIFIED
    assert llm.load_cache(changes.CACHE_PATH) == {}


@pytest.mark.parametrize(
    "kind, noise, content",
    [
        ("scrape-noise", True, False),
        ("cosmetic", False, False),
        ("expansion", False, True),
        ("substantive", False, True),
    ],
)
def test_classification_tiers(kind, noise, content):
    c = changes.Classification(kind=kind, method="llm")
    assert (c.is_noise, c.is_content) == (noise, content)
