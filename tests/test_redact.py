"""De-identification tests. If these pass, the egress claim is defensible."""

from __future__ import annotations

from confidant.redact import Redactor, scan

JP_TEXT = """在留カード番号 AB12345678CD
氏名 山田 太郎様
住居地 東京都港区芝浦4丁目2番8号
電話 03-5555-0123
メール taro.yamada@example.com
マイナンバー 1234 5678 9012
年収 480,000円
"""


def test_residence_card_number_is_removed() -> None:
    r = Redactor().redact(JP_TEXT)
    assert "AB12345678CD" not in r.text
    assert "RESIDENCE_CARD" in r.counts


def test_mynumber_is_removed() -> None:
    r = Redactor().redact(JP_TEXT)
    assert "1234 5678 9012" not in r.text
    assert "MYNUMBER" in r.counts


def test_phone_email_and_address_are_removed() -> None:
    r = Redactor().redact(JP_TEXT)
    for survivor in ("03-5555-0123", "taro.yamada@example.com", "芝浦4丁目2番8号"):
        assert survivor not in r.text
    assert {"PHONE", "EMAIL", "ADDRESS"} <= set(r.counts)


def test_name_before_honorific_is_removed_but_honorific_survives() -> None:
    r = Redactor().redact("山田 太郎様へお知らせします。")
    assert "山田" not in r.text
    assert "様" in r.text


def test_no_residual_pii_after_a_clean_pass() -> None:
    r = Redactor().redact(JP_TEXT)
    assert r.residual_total == 0, r.residual


def test_scan_flags_id_shaped_content_without_modifying_it() -> None:
    hits = scan("カード番号 AB12345678CD です")
    assert hits.get("residence_card") == 1


def test_tokens_are_stable_for_repeated_values() -> None:
    text = "連絡先 a@example.com と、もう一度 a@example.com。"
    r = Redactor().redact(text)
    assert r.text.count("«EMAIL_1»") == 2
    assert r.counts["EMAIL"] == 1  # one distinct value, not two occurrences


def test_distinct_values_get_distinct_tokens() -> None:
    text = "a@example.com と b@example.com"
    r = Redactor().redact(text)
    assert "«EMAIL_1»" in r.text and "«EMAIL_2»" in r.text


def test_redaction_preserves_the_shape_of_a_contradiction() -> None:
    """The whole escalation trick: the cloud sees tokens, the mismatch survives.

    Two different addresses inside one payload must become two *different*
    tokens — otherwise cross-document comparison would be impossible after
    de-identification, and the product's best feature would die with its
    privacy guarantee.
    """
    r = Redactor()
    out = r.redact("住居地 東京都港区芝浦4丁目2番8号\n住居地 東京都渋谷区道玄坂1丁目5番3号")
    assert "«ADDRESS_1»" in out.text
    assert "«ADDRESS_2»" in out.text
    assert out.counts["ADDRESS"] == 2


def test_mapping_is_available_locally_but_excluded_from_the_ledger_view() -> None:
    r = Redactor().redact(JP_TEXT)
    assert r.mapping, "local re-hydration needs the mapping"
    assert "mapping" not in r.as_dict(), "the ledger must never carry originals"
