"""The demo guard exists so a public URL cannot spend your credit.

It is the difference between shipping a live demo and shipping a live invoice.
"""

from __future__ import annotations

from types import SimpleNamespace

from confidant.api import DemoGuard


def guard(cooldown: float = 5.0, cap: int = 3) -> DemoGuard:
    return DemoGuard(SimpleNamespace(per_ip_cooldown_s=cooldown, daily_call_cap=cap))


def test_first_call_passes() -> None:
    g = guard()
    assert g.check("1.1.1.1") is None


def test_second_call_from_the_same_ip_is_throttled() -> None:
    g = guard()
    g.record("1.1.1.1")
    blocked = g.check("1.1.1.1")
    assert blocked is not None
    assert blocked["limited"] is True
    assert "Try again" in blocked["reason"]


def test_a_different_ip_is_not_throttled_by_someone_else() -> None:
    g = guard()
    g.record("1.1.1.1")
    assert g.check("2.2.2.2") is None


def test_daily_cap_refuses_everyone_once_reached() -> None:
    g = guard(cooldown=0.0, cap=2)
    g.record("a")
    g.record("b")
    blocked = g.check("c")
    assert blocked is not None
    assert "Daily demo cap" in blocked["reason"]
    assert "credit pool" in blocked["reason"]


def test_cooldown_zero_disables_the_per_ip_limit() -> None:
    g = guard(cooldown=0.0)
    g.record("1.1.1.1")
    assert g.check("1.1.1.1") is None


def test_used_counts_are_visible_for_the_ui() -> None:
    g = guard(cooldown=0.0)
    g.record("a")
    g.record("b")
    assert g.used == 2
