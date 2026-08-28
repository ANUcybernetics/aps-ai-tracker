"""Unit tests for profile diffing, concept adoption and staleness.

Extraction itself is model-backed and exercised only through the cache; these
tests cover the deterministic logic layered on top of a profile.
"""

from aps_ai_tracker import llm, profiles
from aps_ai_tracker.adoption import build_adoption, staleness
from aps_ai_tracker.profiles import (
    Commitment,
    Profile,
    Step,
    concept_flags,
    diff_profiles,
    extract_profiles,
    standard_report,
)


def make_profile(**overrides) -> Profile:
    base = {
        "summary": "Uses AI for productivity.",
        "intentions_stated": True,
        "usage_patterns": ["workplace-productivity"],
        "domains": ["corporate-and-enabling"],
        "public_facing": "none",
        "public_interaction_commitment": True,
        "monitoring_measures_stated": True,
        "measures": ["staff-training"],
        "accountable_official": "designated",
        "accountable_official_role": "Chief Information Officer",
        "chief_ai_officer": "not-mentioned",
        "chief_ai_officer_role": None,
        "use_case_register": "not-mentioned",
        "staff_training": "available",
        "strategic_position": "not-mentioned",
        "review_cadence": "annual",
        "first_published_stated": "2025-03",
        "last_updated_stated": "2025-03-01",
        "contact_provided": True,
        "named_tools": ["Microsoft 365 Copilot"],
        "policy_version": "v1",
        "policy_compliance_stated": True,
        "legislation_compliance_stated": False,
        "commitments": [
            Commitment(
                text="Will not use AI where the public may directly interact without a human intermediary",
                kind="will-not",
            ),
            Commitment(text="Review the statement annually", kind="will"),
        ],
    }
    base.update(overrides)
    return Profile.model_validate(base)


def test_identical_profiles_have_no_deltas():
    p = make_profile()
    assert diff_profiles(p, p) == []


def test_expansion_without_substance_change_has_no_deltas():
    before = make_profile(summary="Short.")
    after = make_profile(summary="Much longer paraphrase of the same substance.")
    assert diff_profiles(before, after) == []


def test_dropped_commitment_is_significant_and_first():
    before = make_profile()
    after = make_profile(
        public_interaction_commitment=False,
        commitments=[Commitment(text="Review the statement annually", kind="will")],
    )
    deltas = diff_profiles(before, after)
    assert deltas[0].significance == "significant"
    assert deltas[0].direction == "removed"
    fields = {d.field for d in deltas}
    assert fields == {"public_interaction_commitment", "commitments"}


def test_reworded_commitment_still_matches():
    before = make_profile()
    after = make_profile(
        commitments=[
            Commitment(
                text="We will not use AI where members of the public directly interact with it without a human intermediary",
                kind="will-not",
            ),
            Commitment(text="Statement reviewed annually", kind="will"),
        ]
    )
    assert diff_profiles(before, after) == []


def test_officer_appointment_reads_as_notable_addition():
    before = make_profile()
    after = make_profile(chief_ai_officer="in-place", chief_ai_officer_role="COO")
    (delta,) = diff_profiles(before, after)
    assert delta.field == "chief_ai_officer"
    assert delta.direction == "added"
    assert delta.significance == "notable"
    assert "not mentioned → in place" in delta.label


def test_regression_in_ordered_field_is_significant():
    before = make_profile(staff_training="mandatory")
    after = make_profile(staff_training="available")
    (delta,) = diff_profiles(before, after)
    assert (delta.direction, delta.significance) == ("removed", "significant")


def test_list_fields_report_added_and_dropped_items():
    before = make_profile()
    after = make_profile(
        usage_patterns=["workplace-productivity", "analytics-for-insights"],
        named_tools=[],
    )
    deltas = diff_profiles(before, after)
    labels = [d.label for d in deltas]
    assert "Usage pattern added: analytics for insights" in labels
    assert "Named tool dropped: Microsoft 365 Copilot" in labels
    # removals sort ahead of additions of the same significance tier
    assert deltas[0].direction == "removed"


def test_standard_report_reflects_profile():
    report = standard_report(make_profile(legislation_compliance_stated=False))
    assert report["legislation"] is False
    assert report["classification"] is True
    assert set(report) == {key for key, _ in profiles.STANDARD_ELEMENTS}


def test_concept_flags():
    flags = concept_flags(make_profile(chief_ai_officer="planned"))
    assert flags["chief-ai-officer"] is False
    assert flags["chief-ai-officer-planned"] is True
    assert flags["annual-review"] is True
    assert flags["copilot"] is True
    assert flags["policy-v2"] is False


def test_build_adoption_counts_and_transitions():
    p0 = make_profile()
    p1 = make_profile(chief_ai_officer="in-place")
    rows: dict[str, list[tuple[str, str, bool, Profile | None]]] = {
        "A": [
            ("2025-11-11T00:00:00+11:00", "s1", False, p0),
            ("2025-12-20T00:00:00+11:00", "s2", True, p0),  # noise: inherits
            ("2026-02-01T00:00:00+11:00", "s3", False, p1),
        ],
        "B": [("2026-01-15T00:00:00+11:00", "t1", False, p0)],
    }
    out = build_adoption(rows, "2025-11-11T00:00:00+11:00", "2026-02-28T00:00:00+11:00")
    assert out["months"] == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert out["tracked"] == [1, 1, 2, 2]
    caio = next(c for c in out["concepts"] if c["id"] == "chief-ai-officer")
    assert caio["counts"] == [0, 0, 0, 1]
    assert out["transitions"] == [
        {
            "concept": "chief-ai-officer",
            "abbr": "A",
            "date": "2026-02-01T00:00:00+11:00",
            "sha": "s3",
            "direction": "added",
        },
        {
            "concept": "chief-ai-officer-planned",
            "abbr": "A",
            "date": "2026-02-01T00:00:00+11:00",
            "sha": "s3",
            "direction": "added",
        },
    ]


def test_staleness_uses_stated_and_observed_dates():
    built = "2026-08-28T00:00:00+00:00"
    old = staleness(
        make_profile(last_updated_stated="2025-03-01"), None, "2025-11-11", built
    )
    assert old["updatedSincePolicyV2"] is False
    assert old["annualReviewOverdue"] is True

    observed = staleness(
        make_profile(last_updated_stated="2025-03-01"),
        "2026-04-02T00:00:00+11:00",
        "2025-11-11",
        built,
    )
    assert observed["updatedSincePolicyV2"] is True

    month_only = staleness(
        make_profile(last_updated_stated="2025-12"), None, "2025-11-11", built
    )
    assert month_only["updatedSincePolicyV2"] is True  # end of month ≥ 15 Dec
    assert month_only["annualReviewOverdue"] is False

    undated = staleness(
        make_profile(last_updated_stated=None), None, "2025-11-11", built
    )
    assert undated["annualReviewOverdue"] is None

    malformed = staleness(
        make_profile(last_updated_stated="2025"), None, "2025-11-11", built
    )
    assert malformed["annualReviewOverdue"] is None
    assert malformed["statedLastUpdated"] == "2025"


def test_extract_profiles_inherits_across_noise_and_anchors_on_previous(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(profiles, "CACHE_PATH", tmp_path / "profiles.json")
    monkeypatch.setenv("APS_LLM_BACKEND", "api")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p0, p1 = make_profile(), make_profile(chief_ai_officer="in-place")
    # Seed the cache as a previous run would have left it: the first body
    # unanchored, the third anchored on the first body's profile.
    llm.save_cache(
        profiles.CACHE_PATH,
        {
            profiles._chain_key("v1", None): {
                "v": profiles.SCHEMA_VERSION,
                "profile": p0.model_dump(mode="json"),
            },
            profiles._chain_key("v3", p0): {
                "v": profiles.SCHEMA_VERSION,
                "profile": p1.model_dump(mode="json"),
            },
            "stale": {"v": profiles.SCHEMA_VERSION - 1, "profile": {}},
        },
    )
    out = extract_profiles(
        {
            "A": ("Agency A", [Step("v1", True), Step("v2", False), Step("v3", True)]),
            "B": ("Agency B", [Step("new", True)]),
        }
    )
    assert out["A"] == [p0, p0, p1]  # v2 is noise: inherits v1's profile
    assert out["B"] == [None]  # uncached and no backend
    assert "stale" not in llm.load_cache(profiles.CACHE_PATH)
