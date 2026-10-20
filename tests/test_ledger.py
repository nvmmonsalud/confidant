"""Ledger tests: the audit trail has to be tamper-evident, or it is decoration."""

from __future__ import annotations

import json
from pathlib import Path

from confidant.ledger import GENESIS, Ledger


def test_first_record_chains_to_genesis(ledger: Ledger) -> None:
    rec = ledger.append(ledger.new_record(task_id="t1", kind="call", tier="local"))
    assert rec.seq == 0
    assert rec.prev_hash == GENESIS
    assert len(rec.hash) == 64


def test_sequence_and_chain_advance(ledger: Ledger) -> None:
    first = ledger.append(ledger.new_record(task_id="t1", kind="call"))
    second = ledger.append(ledger.new_record(task_id="t2", kind="call"))
    assert second.seq == first.seq + 1
    assert second.prev_hash == first.hash


def test_verify_passes_on_an_untouched_ledger(ledger: Ledger) -> None:
    for i in range(5):
        ledger.append(ledger.new_record(task_id=f"t{i}", kind="call"))
    assert ledger.verify()["ok"] is True
    assert ledger.verify()["checked"] == 5


def test_tampering_with_a_record_is_detected_at_that_seq(ledger: Ledger) -> None:
    for i in range(4):
        ledger.append(ledger.new_record(task_id=f"t{i}", kind="call", cost_usd=0.01))

    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    mutated = json.loads(lines[2])
    mutated["cost_usd"] = 999.0  # rewrite history: "we never spent that"
    lines[2] = json.dumps(mutated, ensure_ascii=False, sort_keys=True)
    ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = ledger.verify()
    assert result["ok"] is False
    assert result["broken_at_seq"] == 2


def test_deleting_a_record_is_detected(ledger: Ledger) -> None:
    for i in range(4):
        ledger.append(ledger.new_record(task_id=f"t{i}", kind="call"))
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert ledger.verify()["ok"] is False


def test_stats_separate_local_from_cloud_tokens(ledger: Ledger) -> None:
    ledger.append(
        ledger.new_record(
            task_id="a", kind="call", tier="local", egress="device", tokens_in=100, tokens_out=50
        )
    )
    ledger.append(
        ledger.new_record(
            task_id="b",
            kind="call",
            tier="tf_deep",
            egress="cloud",
            tokens_in=200,
            tokens_out=20,
            cost_usd=0.001,
        )
    )
    ledger.append(ledger.new_record(task_id="c", kind="refusal", permitted=False))
    stats = ledger.stats()
    assert stats["calls"] == 2
    assert stats["refusals"] == 1
    assert stats["tokens_local"] == 150
    assert stats["tokens_cloud"] == 220
    assert stats["local_share_pct"] == round(100 * 150 / 370, 1)


def test_ledger_survives_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    first = Ledger(path)
    first.append(first.new_record(task_id="a", kind="call"))
    second = Ledger(path)
    rec = second.append(second.new_record(task_id="b", kind="call"))
    assert rec.seq == 1
    assert second.verify()["ok"] is True
