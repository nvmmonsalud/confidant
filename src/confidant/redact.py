"""Japanese-aware de-identification.

Two jobs:

1. Produce a scrubbed string that is safe to send to a cloud tier.
2. Produce a *residual risk* count — how many PII-shaped things survived — so
   the ledger can record a number instead of a promise.

The mapping from token back to original never leaves this process. It is kept
in memory only, and is not serialised into the ledger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Ordered: most specific first, so a MyNumber is not first eaten by PHONE.
# Each entry: (label, compiled pattern, token prefix)
_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "email",
        re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
        "EMAIL",
    ),
    (
        "url",
        re.compile(r"https?://[^\s、。）)]+"),
        "URL",
    ),
    (
        # Residence card: 2 letters, 8 digits, 2 letters (e.g. AB12345678CD)
        "residence_card",
        re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{8}[A-Z]{2}(?![A-Za-z0-9])"),
        "RESIDENCE_CARD",
    ),
    (
        # Passport: 2 letters + 7 digits
        "passport",
        re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{7}(?![A-Za-z0-9])"),
        "PASSPORT",
    ),
    (
        # My Number: 12 digits, optionally grouped 4-4-4
        "mynumber",
        re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)"),
        "MYNUMBER",
    ),
    (
        # Japanese postal code
        "postal",
        re.compile(r"〒\s?\d{3}[-‐ー]\d{4}"),
        "POSTAL",
    ),
    (
        # Japanese street address, up to and including 号
        "address",
        re.compile(
            r"(?:東京都|北海道|(?:京都|大阪)府|.{2,4}県)"
            r"[^\s、。]{0,12}?(?:市|区|郡|町|村)"
            r"[^\s、。]{0,24}?\d+丁目\s?\d+番\s?\d+号?"
        ),
        "ADDRESS",
    ),
    (
        # JP phone: 03-1234-5678 / 090-1234-5678 / +81 90 1234 5678
        "phone",
        re.compile(
            r"(?<!\d)(?:\+81[-\s]?\(?0?\)?|0)\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4}(?!\d)"
        ),
        "PHONE",
    ),
    (
        # Money amounts — not identity, but the numbers people care about
        "money",
        re.compile(r"[¥￥]\s?[\d,]+(?:\.\d+)?|\d[\d,]*\s?円"),
        "MONEY",
    ),
    (
        # Name + honorific. The optional second group catches 山田 太郎様, where
        # a naive pattern would only take 太郎 and leave the surname behind.
        "person",
        re.compile(
            r"([一-龥ぁ-んァ-ヶーA-Za-z]{1,12}(?:[ \t　]+[一-龥ぁ-んァ-ヶーA-Za-z]{1,12})?)"
            r"(?=様|さん|氏|殿)"
        ),
        "PERSON",
    ),
]

#: Things that should never survive a redaction pass. Used for the residual check.
_RESIDUAL_CHECKS = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("residence_card", re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{8}[A-Z]{2}(?![A-Za-z0-9])")),
    ("mynumber", re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)")),
    ("phone", re.compile(r"(?<!\d)0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4}(?!\d)")),
]

#: Names attached to a form label rather than an honorific (氏名 山田 太郎).
_LABELED_NAME = re.compile(
    r"(?P<label>氏名|患者|労働者|世帯主|雇用主|担当)"
    r"(?P<sep>[ \t　]+)"
    r"(?P<name>[^\s、。]{1,12}(?:[ \t　]+[^\s、。]{1,12})?)"
)


@dataclass
class Redaction:
    text: str
    counts: dict[str, int] = field(default_factory=dict)
    mapping: dict[str, str] = field(default_factory=dict)
    residual: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def residual_total(self) -> int:
        return sum(self.residual.values())

    def as_dict(self) -> dict:
        """Ledger-safe view. Note: `mapping` is deliberately excluded."""
        return {
            "counts": dict(self.counts),
            "total": self.total,
            "residual": dict(self.residual),
            "residual_total": self.residual_total,
        }


class Redactor:
    """Deterministic, offline, no model required.

    A learned classifier catches more. A regex pass is auditable, has no
    false-negative tail caused by sampling temperature, and can run before any
    model is loaded — which is the order that matters when the payload is the
    thing you are protecting.
    """

    def __init__(self, extra_entities: list[str] | None = None) -> None:
        self._compiled = list(_PATTERNS)
        # Explicit entities (names from document metadata) get literal matching.
        for ent in extra_entities or []:
            if len(ent.strip()) >= 2:
                self._compiled.insert(
                    0,
                    ("entity", re.compile(re.escape(ent.strip())), "ENTITY"),
                )

    def redact(self, text: str) -> Redaction:
        out = text
        counts: dict[str, int] = {}
        mapping: dict[str, str] = {}
        seen: dict[str, dict[str, str]] = {}

        def _token(label: str, prefix: str, original: str) -> str:
            bucket = seen.setdefault(label, {})
            if original in bucket:
                return bucket[original]
            token = f"«{prefix}_{len(bucket) + 1}»"
            bucket[original] = token
            mapping[token] = original
            return token

        # Pass 1: names that follow a Japanese form label (氏名 山田 太郎).
        # These carry no honorific, so the pattern below would miss them.
        def _label_sub(m: re.Match[str]) -> str:
            name = m.group("name")
            counts["PERSON"] = counts.get("PERSON", 0) + 1
            return f"{m.group('label')}{m.group('sep')}{_token('person', 'PERSON', name)}"

        out = _LABELED_NAME.sub(_label_sub, out)

        # Pass 2: everything pattern-shaped.
        for label, pattern, prefix in self._compiled:
            def _sub(m: re.Match[str], prefix: str = prefix, label: str = label) -> str:
                original = m.group(0)
                if original not in seen.get(label, {}):
                    counts[prefix] = counts.get(prefix, 0) + 1
                return _token(label, prefix, original)

            out = pattern.sub(_sub, out)

        residual: dict[str, int] = {}
        for label, pattern in _RESIDUAL_CHECKS:
            n = len(pattern.findall(out))
            if n:
                residual[label] = n

        return Redaction(text=out, counts=counts, mapping=mapping, residual=residual)


def scan(text: str) -> dict[str, int]:
    """PII-shaped hits without modifying anything. Used by the intake classifier."""
    hits: dict[str, int] = {}
    for label, pattern in _RESIDUAL_CHECKS:
        n = len(pattern.findall(text))
        if n:
            hits[label] = n
    return hits
