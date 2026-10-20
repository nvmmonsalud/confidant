"""End-to-end: ingest -> classify -> decide -> call -> record.

Everything runs against the mock provider, so these tests need no network and
no credit — and they still exercise the real policy engine, the real redactor
and the real hash-chained ledger.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from confidant import router as router_mod
from confidant.config import Settings
from confidant.ledger import Ledger
from confidant.policy import Sensitivity, Tier
from confidant.providers import MockProvider
from confidant.router import Confidant, Vault
from confidant.samples import seed

CROSS_DOC_Q = "Does anything across my documents put my visa renewal at risk?"
WEB_PUBLIC_Q = "What is the current fee for extending a 技術・人文知識・国際業務 visa?"


@pytest.fixture()
def env(tmp_path: Path):
    samples = tmp_path / "samples"
    seed(samples)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    cfg = Settings()  # defaults to mock mode
    vault = Vault(samples, ledger)
    vault.ingest()
    return Confidant(cfg=cfg, ledger=ledger, vault=vault), ledger, samples


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
def test_ingest_classifies_each_document(env) -> None:
    confidant, _, _ = env
    by_id = {d.id: d for d in confidant.vault.docs()}
    assert by_id["residence_card"].sensitivity is Sensitivity.RESTRICTED
    assert by_id["resident_record"].sensitivity is Sensitivity.RESTRICTED
    assert by_id["clinic_note"].sensitivity is Sensitivity.RESTRICTED
    assert by_id["employment_contract"].sensitivity in (
        Sensitivity.SENSITIVE,
        Sensitivity.RESTRICTED,
    )
    assert by_id["grocery_note"].sensitivity is Sensitivity.PERSONAL


def test_ingest_is_recorded_on_device(env) -> None:
    _, ledger, _ = env
    ingests = [r for r in ledger if r.kind == "ingest"]
    assert ingests, "every document that enters the vault must be logged"
    assert all(r.egress == "device" for r in ingests)
    assert ledger.verify()["ok"] is True


# ---------------------------------------------------------------------------
# The default posture: restricted content does not leave
# ---------------------------------------------------------------------------
def test_cross_document_question_stays_local_without_consent(env) -> None:
    confidant, ledger, _ = env
    result = run(confidant.ask(CROSS_DOC_Q))
    assert result["refused"] is False
    assert result["decision"]["tier"] == Tier.LOCAL.value
    assert result["usage"]["cost_usd"] == 0.0
    call = [r for r in ledger if r.kind == "call"][-1]
    assert call.egress == "device"


def test_the_cloud_never_sees_identifier_shaped_content(env, monkeypatch) -> None:
    """The load-bearing test: spy on the prompt that would have been sent."""
    confidant, _, _ = env
    captured: dict[str, str] = {}

    class Spy(MockProvider):
        async def complete(self, system: str, user: str, *, max_tokens: int = 4096):
            captured["prompt"] = user
            return await super().complete(system, user, max_tokens=max_tokens)

    monkeypatch.setattr(router_mod, "build_provider", lambda tier, cfg=None: Spy(tier))

    run(confidant.ask(CROSS_DOC_Q, consent=True))
    prompt = captured["prompt"]
    for secret in ("AB12345678CD", "1234 5678 9012", "03-5555-0123", "港区芝浦4丁目2番8号"):
        assert secret not in prompt, f"{secret!r} leaked into a cloud prompt"


# ---------------------------------------------------------------------------
# Explicit consent unlocks de-identified escalation
# ---------------------------------------------------------------------------
def test_consent_escalates_to_the_deep_tier(env) -> None:
    confidant, ledger, _ = env
    result = run(confidant.ask(CROSS_DOC_Q, consent=True))
    assert result["refused"] is False
    assert result["decision"]["tier"] == Tier.TF_DEEP.value
    assert result["decision"]["redaction_required"] is True
    call = [r for r in ledger if r.kind == "call"][-1]
    assert call.egress == "cloud"
    assert call.redaction["total"] > 0
    assert call.redaction["residual_total"] == 0


def test_the_deep_answer_finds_the_planted_contradiction(env) -> None:
    confidant, _, _ = env
    result = run(confidant.ask(CROSS_DOC_Q, consent=True))
    answer = result["answer"]
    assert "ADDRESS MISMATCH" in answer.upper()
    assert "2027-01-31" in answer


def test_local_tier_is_honest_about_what_it_cannot_do(env) -> None:
    confidant, _, _ = env
    result = run(confidant.ask(CROSS_DOC_Q))
    assert "escalate" in result["answer"].lower()


# ---------------------------------------------------------------------------
# Tavily: topics pass, identifiers do not
# ---------------------------------------------------------------------------
def test_public_topic_lookup_is_allowed(env) -> None:
    confidant, ledger, _ = env
    result = run(confidant.ask(WEB_PUBLIC_Q))
    assert result["refused"] is False
    assert result["web"] is not None
    assert any(r.kind == "web" for r in ledger)


def test_lookup_carrying_an_identifier_is_refused(env) -> None:
    confidant, ledger, _ = env
    result = run(
        confidant.ask(
            "What is the current rule for residence card AB12345678CD?",
            doc_ids=["residence_card"],
        )
    )
    assert result["refused"] is True
    assert result["stage"] == "web"
    assert result["decision"]["reason_code"] == "refused_restricted_web"
    refusal = [r for r in ledger if r.kind == "refusal"][-1]
    assert refusal.permitted is False


def test_refusal_is_written_to_the_ledger_with_a_reason_code(env) -> None:
    confidant, ledger, _ = env
    run(confidant.ask("Is AB12345678CD still current?", doc_ids=["residence_card"]))
    refusal = [r for r in ledger if r.kind == "refusal"][-1]
    assert refusal.reason_code
    assert refusal.egress == "cloud"  # it was refused *at* the boundary
    assert ledger.verify()["ok"] is True


# ---------------------------------------------------------------------------
# Rollups
# ---------------------------------------------------------------------------
def test_stats_show_how_much_stayed_home(env) -> None:
    confidant, _, _ = env
    run(confidant.ask(CROSS_DOC_Q))          # local
    run(confidant.ask(CROSS_DOC_Q, consent=True))  # cloud
    stats = confidant.stats()
    assert stats["calls"] == 2
    assert stats["tokens_local"] > 0
    assert stats["tokens_cloud"] > 0
    assert 0 < stats["local_share_pct"] < 100


def test_ledger_chain_still_verifies_after_a_full_run(env) -> None:
    confidant, ledger, _ = env
    run(confidant.ask(CROSS_DOC_Q))
    run(confidant.ask(CROSS_DOC_Q, consent=True))
    run(confidant.ask(WEB_PUBLIC_Q))
    assert ledger.verify()["ok"] is True
