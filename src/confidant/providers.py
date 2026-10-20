"""Inference providers: one interface, four backends.

    local     Ollama on this machine           (no egress, $0)
    light     Token Factory / Nemotron 3.5 Lightning
    deep      Token Factory / Nemotron 3 Ultra
    mock      deterministic, offline, no credentials

`mock` is a first-class backend, not a test stub. It is the fallback that keeps
the demo alive when the network, the credits, or a quiet Tokyo evening gets in
the way — and it is what makes the test suite hermetic.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Sequence

import httpx

from .config import Settings, settings as default_settings


@dataclass
class Completion:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    provider: str
    latency_ms: int
    finish_reason: str = "stop"


def est_tokens(text: str) -> int:
    """Cheap token estimate. Japanese runs denser than English, so 2.2 not 4."""
    return max(1, int(len(text) / 2.2))


class Provider:
    name = "base"
    model = ""

    async def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> Completion:
        raise NotImplementedError

    async def health(self) -> dict[str, Any]:
        return {"provider": self.name, "ok": True, "model": self.model}


# ---------------------------------------------------------------------------
# Mock — deterministic, and deliberately *tier-aware*.
# ---------------------------------------------------------------------------
class MockProvider(Provider):
    name = "mock"

    def __init__(self, tier: str, model: str = "mock") -> None:
        self.tier = tier
        self.model = model

    async def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> Completion:
        started = time.perf_counter()
        text = self._answer(user)
        return Completion(
            text=text,
            tokens_in=est_tokens(system + user),
            tokens_out=est_tokens(text),
            model=f"{self.model}:{self.tier}",
            provider=self.name,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _answer(self, prompt: str) -> str:
        p = prompt.lower()
        cross_doc = any(
            k in p
            for k in ("across", "all my documents", "contradict", "everything", "risk", "矛盾", "全部")
        )

        if cross_doc:
            if self.tier == "local":
                return (
                    "I can read these documents on this machine, but comparing facts "
                    "across four of them reliably is past what I should answer alone. "
                    "What I can say: your residence card shows an expiry date, and "
                    "there is an employment contract with an end date. I would not "
                    "sign off on a renewal decision from here.\n\n"
                    "Recommendation: escalate this one."
                )
            if self.tier == "light":
                return (
                    "Your 在留カード expires 2027-03-15 (在留資格: 技術・人文知識・国際業務). "
                    "Your employment contract runs to 2027-01-31, so the sponsorship "
                    "is in place through the renewal window. Nothing obviously fatal.\n\n"
                    "Worth double-checking the address on file."
                )
            return (
                "Two things, and the first one is the one that bites.\n\n"
                "1. ADDRESS MISMATCH — your 在留カード lists 港区芝浦4丁目2番8号, but the "
                "住民票 issued after your November 2025 move lists 渋谷区道玄坂1丁目5番3号. "
                "The card even carries a note that the 住居地届出 was never filed. "
                "An unreported address change is the single most common reason a "
                "renewal application gets sent back.\n\n"
                "2. TIMING — visa expiry 2027-03-15, contract end 2027-01-31. The "
                "renewal window opens ~3 months before expiry, i.e. mid-December 2026, "
                "which is *before* your contract ends. That is workable, but you want "
                "the 住居地届出 done well before you file, because they cross-check it.\n\n"
                "Order of operations: file the 住居地届出 at 渋谷区役所 first, then start "
                "the renewal. Do not file the renewal with a stale address on the card."
            )

        if "clinic" in p or "診療" in p:
            return (
                "Your clinic note records lower-back pain and insomnia, a suspected "
                "lumbar disc herniation, loxoprofen 60mg three times daily, and a "
                "follow-up booked for 2026-10-26."
            )
        if "shop" in p or "買い物" in p or "grocery" in p:
            return "Pasta, olive oil, parmigiano, and medium-ground coffee beans."
        return "I read the documents you selected and answered from them."


# ---------------------------------------------------------------------------
# Token Factory (Nebius) — OpenAI-compatible
# ---------------------------------------------------------------------------
class TokenFactoryProvider(Provider):
    name = "token_factory"

    def __init__(self, cfg: Settings, tier: str, model: str) -> None:
        self.cfg = cfg
        self.tier = tier
        self.model = model

    async def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> Completion:
        started = time.perf_counter()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Token Factory serves reasoning models; hidden reasoning bills as
            # output, so a tight cap truncates before the visible answer starts.
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.cfg.nebius_api_key}"}
        async with httpx.AsyncClient(timeout=self.cfg.request_timeout_s) as client:
            resp = await client.post(
                f"{self.cfg.nebius_base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        return Completion(
            text=(choice.get("message") or {}).get("content") or "",
            tokens_in=int(usage.get("prompt_tokens") or est_tokens(system + user)),
            tokens_out=int(usage.get("completion_tokens") or 0),
            model=self.model,
            provider=self.name,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=choice.get("finish_reason") or "stop",
        )


# ---------------------------------------------------------------------------
# Ollama — the local tier
# ---------------------------------------------------------------------------
class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, cfg: Settings, tier: str, model: str) -> None:
        self.cfg = cfg
        self.tier = tier
        self.model = model

    async def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> Completion:
        started = time.perf_counter()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            # Reasoning models (Nemotron 3.5 has this on by default) put the
            # whole budget into `thinking` and return EMPTY content when the
            # cap is reached, with done_reason="length". Off for short factual
            # answers; the ledger records the setting that produced it.
            "think": self.cfg.local_think,
            "options": {"num_predict": max_tokens, "temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=self.cfg.request_timeout_s) as client:
            resp = await client.post(f"{self.cfg.ollama_base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        msg = data.get("message") or {}
        text = msg.get("content") or ""
        # Fall back to the reasoning trace rather than returning nothing.
        if not text.strip():
            text = msg.get("thinking") or ""
        return Completion(
            text=text,
            tokens_in=int(data.get("prompt_eval_count") or est_tokens(system + user)),
            tokens_out=int(data.get("eval_count") or 0),
            model=self.model,
            provider=self.name,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=data.get("done_reason") or "stop",
        )

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{self.cfg.ollama_base_url}/api/tags")
                tags = resp.json().get("models", [])
                names = [t.get("name", "") for t in tags]
                return {
                    "provider": self.name,
                    "ok": True,
                    "model": self.model,
                    "model_present": any(self.model.split(":")[0] in n for n in names),
                    "installed": names[:12],
                }
        except Exception as exc:  # pragma: no cover - environment dependent
            return {"provider": self.name, "ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Tavily
# ---------------------------------------------------------------------------
class TavilyClient:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    async def search(self, query: str, max_results: int = 3) -> dict[str, Any]:
        if not self.cfg.tavily_api_key:
            raise RuntimeError("TAVILY_API_KEY is not set")
        started = time.perf_counter()
        payload = {
            "api_key": self.cfg.tavily_api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": True,
        }
        async with httpx.AsyncClient(timeout=self.cfg.request_timeout_s) as client:
            resp = await client.post(f"{self.cfg.tavily_base_url}/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
        data["latency_ms"] = int((time.perf_counter() - started) * 1000)
        data["query_sent"] = query
        return data


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
class StandInProvider(MockProvider):
    """The device tier on a host that has no device.

    A deployed server has no laptop to be private on, so the local tier cannot
    be real there. Rather than quietly serving it from the cloud — which would
    invert the entire claim — it answers deterministically and says so in the
    model name the ledger records: `…:stand-in`. The video shows the real one.
    """

    name = "stand-in"

    def __init__(self, tier: str, model: str = "mock") -> None:
        super().__init__(tier=tier, model=model)

    async def complete(self, system: str, user: str, *, max_tokens: int = 4096) -> Completion:
        done = await super().complete(system, user, max_tokens=max_tokens)
        done.model = f"{self.model}:stand-in"
        return done


def build_provider(tier: str, cfg: Settings | None = None) -> Provider:
    cfg = cfg or default_settings
    model = {
        "local": cfg.model_local,
        "light": cfg.model_light,
        "deep": cfg.model_deep,
    }[tier]

    if cfg.mode == "mock":
        return MockProvider(tier=tier, model=model)

    if cfg.mode == "hybrid":
        # Cloud is real; the device tier is honest about being a stand-in.
        if tier == "local":
            return StandInProvider(tier=tier, model=model)
        return TokenFactoryProvider(cfg, tier, model)

    # live
    if tier == "local":
        return OllamaProvider(cfg, tier, cfg.model_local)
    return TokenFactoryProvider(cfg, tier, model)


async def probe_token_factory(cfg: Settings | None = None) -> dict[str, Any]:
    """List the live catalogue. Never trust a model id from a blog post."""
    cfg = cfg or default_settings
    if not cfg.nebius_api_key:
        return {"ok": False, "error": "NEBIUS_API_KEY not set"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{cfg.nebius_base_url}/models",
            headers={"Authorization": f"Bearer {cfg.nebius_api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
    ids = sorted(m.get("id", "") for m in data.get("data", []))
    nemotron = [i for i in ids if re.search(r"nemotron", i, re.I)]
    return {"ok": True, "count": len(ids), "nemotron": nemotron, "all": ids}
