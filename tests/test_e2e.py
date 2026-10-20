"""End-to-end over real HTTP.

Unit tests exercise the router directly, which is how a field can be silently
dropped by the request model and still pass the suite. This test spawns the
actual server and speaks to it over the wire, so the HTTP contract is covered.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

CROSS_DOC = "Does anything across my documents put my visa renewal at risk?"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    samples = tmp / "samples"
    samples.mkdir()

    sys.path.insert(0, str(ROOT / "src"))
    from confidant.samples import seed

    seed(samples)

    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "CONFIDANT_MODE": "mock",
        "CONFIDANT_DATA": str(tmp),
        "CONFIDANT_LEDGER": str(tmp / "ledger.jsonl"),
        # The demo guard throttles per IP; the test suite fires from one IP by
        # design, so it must be off here and asserted separately.
        "CONFIDANT_PER_IP_COOLDOWN": "0",
        "CONFIDANT_DAILY_CAP": "10000",
    }
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "confidant.api:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"

    deadline = time.time() + 25
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
            pytest.fail(f"server exited during startup:\n{out}")
        try:
            if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.25)
    else:
        proc.terminate()
        pytest.fail("server did not become healthy in 25s")

    yield base

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_health_reports_six_classified_documents(server) -> None:
    h = httpx.get(f"{server}/api/health", timeout=5).json()
    assert h["ok"] is True
    assert h["mode"] == "mock"
    assert h["docs"] == 6
    assert set(h["tiers"]) == {"local", "tf_light", "tf_deep"}


def test_the_ui_actually_serves(server) -> None:
    r = httpx.get(f"{server}/", timeout=5)
    assert r.status_code == 200
    assert "Confidant" in r.text
    assert "/api/ask" in r.text


def test_default_posture_is_local(server) -> None:
    r = httpx.post(
        f"{server}/api/ask", json={"question": CROSS_DOC, "consent": False}, timeout=20
    ).json()
    assert r["refused"] is False
    assert r["decision"]["tier"] == "local"
    assert r["usage"]["cost_usd"] == 0.0


def test_consent_reaches_the_router_over_http(server) -> None:
    """The regression this file exists for: `consent` must survive the request model."""
    r = httpx.post(
        f"{server}/api/ask", json={"question": CROSS_DOC, "consent": True}, timeout=20
    ).json()
    assert r["refused"] is False
    assert r["decision"]["tier"] == "tf_deep", r["decision"]
    assert r["decision"]["redaction_required"] is True
    assert r["usage"]["cost_usd"] > 0


def test_identifier_bearing_lookup_is_refused(server) -> None:
    r = httpx.post(
        f"{server}/api/ask",
        json={"question": "What is the current rule for residence card AB12345678CD?"},
        timeout=20,
    ).json()
    assert r["refused"] is True
    assert r["decision"]["reason_code"] == "refused_restricted_web"


def test_ledger_verifies_and_reports_stats(server) -> None:
    data = httpx.get(f"{server}/api/ledger?limit=50", timeout=10).json()
    assert data["integrity"]["ok"] is True
    stats = data["stats"]
    assert stats["calls"] >= 2
    assert stats["refusals"] >= 1
    assert stats["tokens_local"] > 0
    assert stats["tokens_cloud"] > 0
    assert stats["cost_usd"] > 0
