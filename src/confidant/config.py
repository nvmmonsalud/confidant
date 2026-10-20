"""Runtime configuration.

Every model id here is a *default*, not a truth claim. Confirm them against
``GET /v1/models`` on Token Factory before trusting any of it:

    python scripts/probe_models.py

Nebius rotates catalogue names (``Nemotron-3_5-Lightning`` vs
``nemotron-3.5-lightning-30b-a3b`` both appear in the wild).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("CONFIDANT_DATA", REPO_ROOT / "data"))
LEDGER_PATH = Path(os.environ.get("CONFIDANT_LEDGER", DATA_DIR / "ledger.jsonl"))
# Overridable because on a serverless host the package does not sit two
# directories below the repo root.
WEB_DIR = Path(os.environ.get("CONFIDANT_WEB", REPO_ROOT / "web"))


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    """Resolved at import; overridden entirely by environment variables."""

    # --- Nebius Token Factory ------------------------------------------------
    nebius_api_key: str = field(default_factory=lambda: _env("NEBIUS_API_KEY"))
    # Hermes ships a native `nebius-token-factory` provider; this is the same host.
    nebius_base_url: str = field(
        default_factory=lambda: (
            _env("CONFIDANT_NEBIUS_BASE_URL")
            or _env("NEBIUS_BASE_URL")
            or "https://api.studio.nebius.com/v1"
        ).rstrip("/")
    )
    model_light: str = field(
        default_factory=lambda: _env(
            "CONFIDANT_MODEL_LIGHT", "nvidia/nemotron-3.5-lightning-30b-a3b"
        )
    )
    model_deep: str = field(
        default_factory=lambda: _env(
            "CONFIDANT_MODEL_DEEP", "nvidia/Nemotron-3-Ultra-550b-a55b"
        )
    )

    # --- Local tier (Ollama) -------------------------------------------------
    # Prefixed first: Hermes' own .env sets OLLAMA_BASE_URL to Ollama *Cloud*,
    # and inheriting that would silently send "local" inference to the internet
    # — the exact inversion this project exists to prevent.
    ollama_base_url: str = field(
        default_factory=lambda: (
            _env("CONFIDANT_OLLAMA_BASE_URL")
            or _env("OLLAMA_BASE_URL")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
    )
    model_local: str = field(
        default_factory=lambda: _env("CONFIDANT_MODEL_LOCAL", "nemotron-3.5-lightning:30b-mlx")
    )
    # A vision-capable local model is what makes on-device ingestion honest.
    model_local_vision: str = field(
        default_factory=lambda: _env(
            "CONFIDANT_MODEL_LOCAL_VISION", "nemotron-3.5-bolt:74b-a9b"
        )
    )

    # --- Tavily --------------------------------------------------------------
    tavily_api_key: str = field(default_factory=lambda: _env("TAVILY_API_KEY"))
    tavily_base_url: str = field(
        default_factory=lambda: (
            _env("CONFIDANT_TAVILY_BASE_URL")
            or _env("TAVILY_BASE_URL")
            or "https://api.tavily.com"
        ).rstrip("/")
    )

    # --- Behaviour -----------------------------------------------------------
    # "mock"   -> deterministic, offline, zero credentials. Full policy demo.
    # "hybrid" -> cloud tiers are real (Token Factory), the device tier is a
    #             clearly-labelled stand-in. This is what the hosted demo runs:
    #             a server has no laptop to be private on.
    # "live"   -> everything real, including Ollama on this machine.
    mode: str = field(default_factory=lambda: _env("CONFIDANT_MODE", "mock").lower())
    request_timeout_s: float = field(
        default_factory=lambda: float(_env("CONFIDANT_TIMEOUT", "120"))
    )
    # Reasoning models spend their whole budget in `thinking` and return empty
    # content when the cap is hit. Off by default for short factual answers.
    local_think: bool = field(
        default_factory=lambda: _env("CONFIDANT_LOCAL_THINK", "0").lower()
        in ("1", "true", "yes")
    )
    # Demo guardrails, so a public URL cannot drain the credit pool.
    per_ip_cooldown_s: float = field(
        default_factory=lambda: float(_env("CONFIDANT_PER_IP_COOLDOWN", "5"))
    )
    daily_call_cap: int = field(
        default_factory=lambda: int(_env("CONFIDANT_DAILY_CAP", "300"))
    )

    @property
    def live(self) -> bool:
        return self.mode == "live"

    @property
    def hybrid(self) -> bool:
        return self.mode == "hybrid"

    def missing_credentials(self) -> list[str]:
        """What a live run still needs. Empty list means we're good to go."""
        missing: list[str] = []
        if self.mode in ("live", "hybrid") and not self.nebius_api_key:
            missing.append("NEBIUS_API_KEY")
        if self.live and not self.tavily_api_key:
            missing.append("TAVILY_API_KEY")
        return missing


settings = Settings()


# USD per 1M tokens (input, output). Published Token Factory rates as of Oct 2026.
# Re-check at https://nebius.com/prices before quoting these in a demo.
PRICING: dict[str, tuple[float, float]] = {
    "light": (0.06, 0.24),
    "deep": (1.00, 3.00),
    "local": (0.00, 0.00),
}


def cost_usd(tier_key: str, tokens_in: int, tokens_out: int) -> float:
    p_in, p_out = PRICING[tier_key]
    return round(tokens_in / 1e6 * p_in + tokens_out / 1e6 * p_out, 6)
