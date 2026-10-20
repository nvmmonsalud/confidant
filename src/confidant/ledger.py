"""Append-only, hash-chained decision ledger.

Every routing decision — including the refusals — becomes a line in a JSONL
file whose each record carries the hash of the record before it. Tamper with
one entry and `verify()` fails at exactly that sequence number.

This is the artifact that turns "we respect your privacy" into a claim a third
party can check, which is the entire difference between a privacy feature and
a privacy product.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

GENESIS = "0" * 64


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _digest(payload: dict[str, Any], prev_hash: str) -> str:
    blob = json.dumps(
        {"prev": prev_hash, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass
class Record:
    seq: int = 0
    ts: str = ""
    task_id: str = ""
    kind: str = ""                 # "ingest" | "decision" | "call" | "refusal" | "web"
    question: str = ""
    doc_ids: list[str] = field(default_factory=list)
    sensitivity: str = "public"
    tier: str | None = None
    model: str | None = None
    egress: str = "device"
    reason_code: str = ""
    reason: str = ""
    permitted: bool = True
    redaction: dict[str, Any] = field(default_factory=dict)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    prev_hash: str = GENESIS
    hash: str = ""

    def payload(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("hash", None)
        d.pop("prev_hash", None)
        return d


class Ledger:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.touch()

    # -- write ------------------------------------------------------------
    def append(self, record: Record) -> Record:
        with self._lock:
            last = self._last_record()
            record.seq = (last.seq + 1) if last else 0
            record.ts = record.ts or _utc_now()
            record.prev_hash = last.hash if last else GENESIS
            record.hash = _digest(record.payload(), record.prev_hash)
            line = json.dumps(asdict(record), ensure_ascii=False, sort_keys=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return record

    def new_record(self, **kwargs: Any) -> Record:
        return Record(ts=_utc_now(), **kwargs)

    # -- read -------------------------------------------------------------
    def __iter__(self) -> Iterator[Record]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                yield Record(**raw)

    def records(self) -> list[Record]:
        return list(self)

    def _last_record(self) -> Record | None:
        last: Record | None = None
        for rec in self:
            last = rec
        return last

    def tail(self, n: int = 50) -> list[Record]:
        recs = self.records()
        return recs[-n:][::-1]

    # -- integrity --------------------------------------------------------
    def verify(self) -> dict[str, Any]:
        prev = GENESIS
        count = 0
        for rec in self:
            expected = _digest(rec.payload(), prev)
            if rec.prev_hash != prev or rec.hash != expected:
                return {
                    "ok": False,
                    "checked": count,
                    "broken_at_seq": rec.seq,
                    "detail": "hash chain mismatch — record was modified or removed",
                }
            prev = rec.hash
            count += 1
        return {"ok": True, "checked": count, "broken_at_seq": None, "head": prev}

    # -- rollups ----------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        calls = 0
        refusals = 0
        by_tier: dict[str, int] = {}
        tokens_local = 0
        tokens_cloud = 0
        cost = 0.0
        redacted_docs = 0
        for rec in self:
            if rec.kind == "refusal" or not rec.permitted:
                refusals += 1
            if rec.kind == "call":
                calls += 1
                by_tier[rec.tier or "unknown"] = by_tier.get(rec.tier or "unknown", 0) + 1
                if rec.egress == "device":
                    tokens_local += rec.tokens_in + rec.tokens_out
                else:
                    tokens_cloud += rec.tokens_in + rec.tokens_out
                cost += rec.cost_usd
                if rec.redaction.get("total"):
                    redacted_docs += 1
        total_tokens = tokens_local + tokens_cloud
        return {
            "calls": calls,
            "refusals": refusals,
            "by_tier": by_tier,
            "tokens_local": tokens_local,
            "tokens_cloud": tokens_cloud,
            "local_share_pct": round(100 * tokens_local / total_tokens, 1) if total_tokens else 0.0,
            "cost_usd": round(cost, 6),
            "redacted_requests": redacted_docs,
        }
