"""Sensitivity classification, on-device and deterministic.

The classifier runs *before* any model does. It has to: the thing you are
protecting is the document, so the decision about whether the document may
leave has to be made by something that cannot itself leak it.

A keyword table is unglamorous, and that is the point — it is auditable, it
has no sampling tail, and a judge can diff it. The model-assisted tier
(Bolt E4B) is an upgrade path, not a dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .policy import Sensitivity
from .redact import scan

# Multi-word signals first; a single strong hit is enough to escalate.
_RESTRICTED_SIGNALS: list[tuple[str, str]] = [
    ("residence_card_kw", r"在留カード|在留資格|在留期限|residence card|zairyu"),
    ("immigration", r"出入国在留管理庁|入管|ビザ|visa|永住|帰化"),
    ("mynumber", r"マイナンバー|個人番号|my number"),
    ("passport", r"パスポート|旅券|passport"),
    ("medical", r"診断書|カルテ|処方|病歴|診療|medical record|prescription|diagnos"),
    ("insurance_card", r"健康保険証|保険証|health insurance"),
    ("tax_doc", r"課税証明|住民税|確定申告|源泉徴収|tax return|withholding"),
    ("bank_secret", r"暗証番号|口座番号|キャッシュカード|routing number"),
    ("credential", r"api[_-]?key|secret[_-]?key|パスワード|password"),

    # "pension" reads as restricted because the notices carry 基礎年金番号
    ("pension", r"年金|pension"),
    ("municipal_registry", r"住民票|戸籍|住民基本台帳"),
]

_SENSITIVE_SIGNALS: list[tuple[str, str]] = [
    ("employment", r"雇用契約|労働条件|就業規則|employment contract|offer letter"),
    ("income", r"給与|年収|給料|salary|compensation"),
    ("finance", r"ローン|借入|返済|残高|loan|mortgage|balance"),
    ("housing", r"賃貸|家賃|管理費|lease|rent"),
    ("family", r"家族|配偶者|扶養|spouse|dependent"),
    ("health_soft", r"通院|服薬|メンタル|therapy|counsel"),
]

_PERSONAL_SIGNALS: list[tuple[str, str]] = [
    ("schedule", r"予定|カレンダー|schedule|calendar"),
    ("notes", r"メモ|日記|journal|notes"),
    ("preference", r"好み|苦手|prefer|dislike|allerg"),
]

_COMPILED = [
    (Sensitivity.RESTRICTED, [(n, re.compile(p, re.IGNORECASE)) for n, p in _RESTRICTED_SIGNALS]),
    (Sensitivity.SENSITIVE, [(n, re.compile(p, re.IGNORECASE)) for n, p in _SENSITIVE_SIGNALS]),
    (Sensitivity.PERSONAL, [(n, re.compile(p, re.IGNORECASE)) for n, p in _PERSONAL_SIGNALS]),
]


@dataclass
class Classification:
    sensitivity: Sensitivity
    signals: list[str] = field(default_factory=list)
    evidence: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "sensitivity": self.sensitivity.value,
            "signals": list(self.signals),
            "evidence": dict(self.evidence),
        }


def classify(text: str, title: str = "") -> Classification:
    """Return the highest sensitivity any rule can justify, with its evidence."""
    haystack = f"{title}\n{text}"
    best = Sensitivity.PUBLIC
    signals: list[str] = []
    evidence: dict[str, int] = {}

    # Hard evidence beats keywords: an actual ID-shaped string in the content.
    pii = scan(haystack)
    if pii:
        signals.extend(f"pii:{k}" for k in pii)
        evidence.update({f"pii:{k}": v for k, v in pii.items()})
        best = Sensitivity.RESTRICTED

    for level, patterns in _COMPILED:
        hits = [name for name, pat in patterns if pat.search(haystack)]
        if hits:
            signals.extend(hits)
            for name in hits:
                evidence[name] = 1
            if _rank(level) > _rank(best):
                best = level

    return Classification(sensitivity=best, signals=signals, evidence=evidence)


def _rank(s: Sensitivity) -> int:
    return {
        Sensitivity.PUBLIC: 0,
        Sensitivity.PERSONAL: 1,
        Sensitivity.SENSITIVE: 2,
        Sensitivity.RESTRICTED: 3,
    }[s]


def classify_outbound(text: str) -> Classification:
    """Sensitivity of a string that is *about to leave*, e.g. a search query.

    Topics are not payloads. "What is the fee for a 技人国 visa?" mentions
    immigration and carries nothing personal; it must not be refused.
    "Look up AB12345678CD" carries an identifier and must be.

    So this uses only hard PII shapes — identifiers — not topical keywords.
    """
    pii = scan(text)
    if pii:
        return Classification(
            sensitivity=Sensitivity.RESTRICTED,
            signals=[f"pii:{k}" for k in pii],
            evidence={f"pii:{k}": v for k, v in pii.items()},
        )
    return Classification(sensitivity=Sensitivity.PUBLIC, signals=[], evidence={})
