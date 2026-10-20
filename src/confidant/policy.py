"""The routing policy. This is the product.

Most "privacy routers" decide on cost. Ours decides on **data residency first**
and cost second: a document that is not permitted to leave the device does not
leave the device even when sending it would be cheaper *and* give a better
answer. Cost is the tiebreaker among tiers that are already allowed.

The policy is deliberately small, explicit, and auditable — a judge can read
this file and know exactly what the system will and will not do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Sensitivity(str, Enum):
    """Ordered least -> most sensitive. Documents inherit the max of their parts."""

    PUBLIC = "public"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


_RANK = {
    Sensitivity.PUBLIC: 0,
    Sensitivity.PERSONAL: 1,
    Sensitivity.SENSITIVE: 2,
    Sensitivity.RESTRICTED: 3,
}


def max_sensitivity(values: list[Sensitivity]) -> Sensitivity:
    if not values:
        return Sensitivity.PUBLIC
    return max(values, key=lambda s: _RANK[s])


class Tier(str, Enum):
    LOCAL = "local"          # on-device, no egress
    TF_LIGHT = "tf_light"    # Nebius Token Factory, Nemotron 3.5 Lightning
    TF_DEEP = "tf_deep"      # Nebius Token Factory, Nemotron 3 Ultra


class Egress(str, Enum):
    DEVICE = "device"
    CLOUD = "cloud"


@dataclass(frozen=True)
class TierSpec:
    key: Tier
    label: str
    egress: Egress
    vision: bool
    price_key: str          # into config.PRICING
    blurb: str


TIERS: dict[Tier, TierSpec] = {
    Tier.LOCAL: TierSpec(
        Tier.LOCAL,
        "Local — on this device",
        Egress.DEVICE,
        vision=True,
        price_key="local",
        blurb="On this machine. Nothing leaves.",
    ),
    Tier.TF_LIGHT: TierSpec(
        Tier.TF_LIGHT,
        "Token Factory — Nemotron 3.5 Lightning",
        Egress.CLOUD,
        vision=False,
        price_key="light",
        blurb="Execution layer. Cheap, fast, tool-shaped work.",
    ),
    Tier.TF_DEEP: TierSpec(
        Tier.TF_DEEP,
        "Token Factory — Nemotron 3 Ultra",
        Egress.CLOUD,
        vision=False,
        price_key="deep",
        blurb="Escalation. Long recall, contradictions, numbers.",
    ),
}

# Cheapest-forbidden-first ordering used when picking among permitted tiers.
_CHEAPEST_FIRST = [Tier.LOCAL, Tier.TF_LIGHT, Tier.TF_DEEP]


class Capability(str, Enum):
    VISION = "vision"           # must be able to see the source document
    WEB = "web"                 # will hit Tavily (third-party egress)
    LONG_CONTEXT = "long_context"  # needs >100k tokens of recall


@dataclass
class Decision:
    permitted: bool
    tier: Tier | None
    reason_code: str
    reason: str
    sensitivity: Sensitivity
    redaction_required: bool = False
    allowed_tiers: list[Tier] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "permitted": self.permitted,
            "tier": self.tier.value if self.tier else None,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "sensitivity": self.sensitivity.value,
            "redaction_required": self.redaction_required,
            "allowed_tiers": [t.value for t in self.allowed_tiers],
        }


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------

#: Sensitivity at or below which cloud tiers are allowed with raw content.
CLOUD_CLEARANCE = Sensitivity.PERSONAL


def allowed_tiers(
    sensitivity: Sensitivity,
    *,
    redacted: bool = False,
    consent: bool = False,
    residual: int = 0,
) -> list[Tier]:
    """Which tiers may legally receive this content, in preference order.

    - The local tier is always allowed: it is the floor.
    - Cloud needs either low sensitivity, or content that has been de-identified.
    - ``RESTRICTED`` reaches the cloud only under an explicit per-request
      consent *and* a clean redaction (``residual == 0``). Both conditions are
      recorded in the ledger, so the exception is visible rather than implied.
    """
    if _RANK[sensitivity] <= _RANK[CLOUD_CLEARANCE]:
        return list(_CHEAPEST_FIRST)
    if sensitivity is Sensitivity.SENSITIVE and redacted:
        return list(_CHEAPEST_FIRST)
    if sensitivity is Sensitivity.RESTRICTED and redacted and consent and residual == 0:
        return list(_CHEAPEST_FIRST)
    return [Tier.LOCAL]


def decide(
    sensitivity: Sensitivity,
    *,
    capabilities: set[Capability] | None = None,
    est_tokens: int = 0,
    redaction_available: bool = True,
    consent: bool = False,
    residual: int = 0,
) -> Decision:
    """Pick the cheapest tier that is *permitted* and *capable*.

    Returns a refusal — never a silent downgrade — when no permitted tier can
    do the job. A visible refusal is the point of the system; doing the work
    anyway and hoping nobody notices is what this project exists to replace.
    """
    capabilities = capabilities or set()

    # 1. A vision task on sensitive material cannot be done in the cloud: the
    #    document itself would have to be uploaded to read it. Redaction does
    #    not help, because the pixels ARE the payload.
    if Capability.VISION in capabilities and _RANK[sensitivity] >= _RANK[Sensitivity.SENSITIVE]:
        return Decision(
            permitted=True,
            tier=Tier.LOCAL,
            reason_code="vision_pinned_local",
            reason="Document must be read where it lives; no cloud vision permitted.",
            sensitivity=sensitivity,
            allowed_tiers=[Tier.LOCAL],
        )

    # 2. A web lookup with restricted content is egress by definition.
    if Capability.WEB in capabilities and sensitivity is Sensitivity.RESTRICTED:
        return Decision(
            permitted=False,
            tier=None,
            reason_code="refused_restricted_web",
            reason=(
                "Refused: a web search would transmit restricted content to a "
                "third party. De-identify the query first, or keep it local."
            ),
            sensitivity=sensitivity,
            allowed_tiers=[Tier.LOCAL],
        )

    # 3. Long-context recall is the one job the cheap tiers genuinely fail, so
    #    the escalation has to be explicit rather than discovered by a bad answer.
    needs_deep = Capability.LONG_CONTEXT in capabilities or est_tokens > 100_000

    permitted = allowed_tiers(
        sensitivity,
        redacted=(_RANK[sensitivity] > _RANK[CLOUD_CLEARANCE]) and redaction_available,
        consent=consent,
        residual=residual,
    )
    capable = permitted
    if Capability.VISION in capabilities:
        capable = [t for t in permitted if TIERS[t].vision]
    if needs_deep:
        # Ultra is the only cloud tier with the long-recall advantage; local
        # still qualifies if it is explicitly the only permitted destination.
        capable = [t for t in capable if t is not Tier.TF_LIGHT]

    if not capable:
        return Decision(
            permitted=False,
            tier=None,
            reason_code="refused_no_permitted_tier",
            reason=(
                f"Refused: nothing permitted for {sensitivity.value} content can "
                "satisfy this request."
            ),
            sensitivity=sensitivity,
            allowed_tiers=permitted,
        )

    tier = capable[-1] if needs_deep else capable[0]

    # 4. Sensitive-but-not-restricted content needs the scrubber before egress.
    redaction_required = (
        TIERS[tier].egress is Egress.CLOUD
        and _RANK[sensitivity] > _RANK[CLOUD_CLEARANCE]
    )
    if redaction_required and not redaction_available:
        return Decision(
            permitted=False,
            tier=None,
            reason_code="refused_no_redactor",
            reason="Refused: egress needs de-identification and none is available.",
            sensitivity=sensitivity,
            allowed_tiers=permitted,
        )

    if tier is Tier.LOCAL:
        code, why = "local_only_floor", "Stays on device by policy."
    elif needs_deep:
        code, why = "escalated_for_recall", "Long-context recall requires the deep tier."
    elif tier is Tier.TF_LIGHT:
        code, why = "cheapest_permitted", "Cheapest tier permitted for this content."
    else:
        code, why = "deep_permitted", "Deep tier permitted and required."

    return Decision(
        permitted=True,
        tier=tier,
        reason_code=code,
        reason=why,
        sensitivity=sensitivity,
        redaction_required=redaction_required,
        allowed_tiers=permitted,
    )
