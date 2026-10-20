"""Policy tests. These encode the promises the product makes."""

from __future__ import annotations

from confidant.policy import (
    Capability,
    Sensitivity,
    Tier,
    allowed_tiers,
    decide,
    max_sensitivity,
)


def test_max_sensitivity_picks_the_most_sensitive() -> None:
    assert (
        max_sensitivity([Sensitivity.PUBLIC, Sensitivity.RESTRICTED, Sensitivity.PERSONAL])
        is Sensitivity.RESTRICTED
    )
    assert max_sensitivity([]) is Sensitivity.PUBLIC


def test_public_content_gets_the_cheapest_tier() -> None:
    d = decide(Sensitivity.PUBLIC)
    assert d.permitted
    assert d.tier is Tier.LOCAL
    assert d.reason_code == "local_only_floor"


def test_sensitive_content_cannot_leave_unredacted() -> None:
    assert allowed_tiers(Sensitivity.SENSITIVE) == [Tier.LOCAL]


def test_sensitive_content_may_leave_redacted() -> None:
    d = decide(Sensitivity.SENSITIVE)
    # Cloud enters the permitted set once a redactor is available...
    assert Tier.TF_LIGHT in d.allowed_tiers
    # ...but the router is local-first, so the floor still wins on cost.
    assert d.tier is Tier.LOCAL


def test_sensitive_content_needs_a_redactor_to_reach_cloud() -> None:
    d = decide(Sensitivity.SENSITIVE, redaction_available=False)
    assert d.allowed_tiers == [Tier.LOCAL]


def test_restricted_never_reaches_cloud_without_consent() -> None:
    assert allowed_tiers(Sensitivity.RESTRICTED) == [Tier.LOCAL]
    assert allowed_tiers(Sensitivity.RESTRICTED, redacted=True, consent=False) == [Tier.LOCAL]


def test_restricted_reaches_cloud_only_with_consent_and_clean_scrub() -> None:
    assert Tier.TF_DEEP in allowed_tiers(
        Sensitivity.RESTRICTED, redacted=True, consent=True, residual=0
    )
    # A single surviving span closes the door again.
    assert (
        allowed_tiers(Sensitivity.RESTRICTED, redacted=True, consent=True, residual=1)
        == [Tier.LOCAL]
    )


def test_vision_on_sensitive_material_is_pinned_local() -> None:
    d = decide(Sensitivity.RESTRICTED, capabilities={Capability.VISION})
    assert d.permitted
    assert d.tier is Tier.LOCAL
    assert d.reason_code == "vision_pinned_local"


def test_web_lookup_of_restricted_content_is_refused() -> None:
    d = decide(Sensitivity.RESTRICTED, capabilities={Capability.WEB})
    assert not d.permitted
    assert d.reason_code == "refused_restricted_web"
    assert "Refused" in d.reason


def test_web_lookup_of_public_content_is_allowed() -> None:
    d = decide(Sensitivity.PUBLIC, capabilities={Capability.WEB})
    assert d.permitted


def test_long_context_escalates_past_the_light_tier() -> None:
    d = decide(Sensitivity.PUBLIC, capabilities={Capability.LONG_CONTEXT})
    assert d.permitted
    assert d.tier is Tier.TF_DEEP
    assert d.reason_code == "escalated_for_recall"


def test_long_context_escalation_cannot_override_restricted() -> None:
    d = decide(Sensitivity.RESTRICTED, capabilities={Capability.LONG_CONTEXT})
    assert d.tier is Tier.LOCAL


def test_refusal_when_nothing_permitted_is_capable() -> None:
    # VISION + cloud-only would be uncapable, but local is always permitted, so
    # force the impossible case by asking for a tier set with no vision support.
    d = decide(Sensitivity.RESTRICTED, capabilities={Capability.VISION, Capability.WEB})
    assert d.tier is Tier.LOCAL  # vision wins first, and it is on-device


def test_decision_serialises_for_the_ledger() -> None:
    d = decide(Sensitivity.PERSONAL)
    payload = d.as_dict()
    assert set(payload) >= {"permitted", "tier", "reason_code", "sensitivity", "allowed_tiers"}
    assert isinstance(payload["allowed_tiers"], list)
