"""HTTP surface. Deliberately small: the UI is one page and everything it needs
is on this API.
"""

from __future__ import annotations

import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from pydantic import BaseModel, Field

from . import policy
from .config import DATA_DIR, LEDGER_PATH, REPO_ROOT, WEB_DIR, settings
from .ledger import Ledger
from .providers import probe_token_factory
from .router import Confidant, Vault


class DemoGuard:
    """Keeps a public URL from draining a credit pool.

    The site is unauthenticated, so anyone with the link can press the button
    that costs money. A per-IP cooldown plus a global daily ceiling means the
    worst case is a few dollars, and the ceiling is visible in the UI rather
    than discovered on the invoice.
    """

    def __init__(self, config) -> None:
        self.cfg = config
        self._last_seen: dict[str, float] = defaultdict(float)
        self._day = ""
        self._count = 0

    def _roll(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today != self._day:
            self._day = today
            self._count = 0

    def check(self, ip: str) -> dict[str, Any] | None:
        self._roll()
        if self._count >= self.cfg.daily_call_cap:
            return {
                "limited": True,
                "reason": (
                    f"Daily demo cap reached ({self.cfg.daily_call_cap} live calls). "
                    "This ceiling exists so a public URL cannot drain the credit pool; "
                    "run the project locally for unlimited calls."
                ),
            }
        wait = self.cfg.per_ip_cooldown_s - (time.monotonic() - self._last_seen[ip])
        if wait > 0:
            return {
                "limited": True,
                "reason": f"One live call every {self.cfg.per_ip_cooldown_s:.0f}s. "
                f"Try again in {wait:.1f}s.",
            }
        return None

    def record(self, ip: str) -> None:
        self._roll()
        self._last_seen[ip] = time.monotonic()
        self._count += 1

    @property
    def used(self) -> int:
        self._roll()
        return self._count


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not vault.docs():
        vault.ingest()
    yield


app = FastAPI(title="Confidant", version="0.1.0", docs_url="/api/docs", lifespan=lifespan)

ledger = Ledger(LEDGER_PATH)
vault = Vault(DATA_DIR / "samples", ledger)
confidant = Confidant(cfg=settings, ledger=ledger, vault=vault)
guard = DemoGuard(settings)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    doc_ids: list[str] | None = None
    allow_web: bool = True
    # Explicit per-request opt-in to de-identified escalation. Absent by
    # default; a client that does not send it can never cause an egress.
    consent: bool = False


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": settings.mode,
        "tiers": {
            t.value: {
                "label": spec.label,
                "egress": spec.egress.value,
                "vision": spec.vision,
                "blurb": spec.blurb,
            }
            for t, spec in policy.TIERS.items()
        },
        "models": {
            "local": settings.model_local,
            "light": settings.model_light,
            "deep": settings.model_deep,
        },
        "docs": len(vault.docs()),
        "ledger": str(ledger.path),
    }


@app.get("/api/docs")
async def list_docs() -> dict[str, Any]:
    if not vault.docs():
        vault.ingest()
    return {"docs": [d.as_dict() for d in vault.docs()]}


@app.get("/api/ledger")
async def get_ledger(limit: int = 60) -> dict[str, Any]:
    recs = ledger.tail(limit)
    return {
        "records": [r.__dict__ for r in recs],
        "stats": confidant.stats(),
        "integrity": ledger.verify(),
    }


@app.post("/api/ask")
async def ask(req: AskRequest, request: Request) -> JSONResponse:
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    blocked = guard.check(ip)
    if blocked:
        return JSONResponse(
            {
                "task_id": "throttled",
                "question": req.question,
                "refused": True,
                "stage": "guard",
                "answer": blocked["reason"],
                "decision": {
                    "permitted": False,
                    "tier": None,
                    "reason_code": "demo_quota",
                    "reason": blocked["reason"],
                    "sensitivity": "public",
                    "redaction_required": False,
                    "allowed_tiers": [],
                },
                "tier_label": "—",
                "model": None,
                "web": None,
                "usage": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "latency_ms": 0},
                "ledger_seqs": [],
            },
            status_code=429,
        )
    guard.record(ip)
    result = await confidant.ask(
        req.question, req.doc_ids, allow_web=req.allow_web, consent=req.consent
    )
    result["stats"] = confidant.stats()
    result["demo_calls_used"] = guard.used
    result["demo_call_cap"] = settings.daily_call_cap
    return JSONResponse(result)


@app.get("/api/verify")
async def verify() -> dict[str, Any]:
    return ledger.verify()


@app.post("/api/reingest")
async def reingest() -> dict[str, Any]:
    docs = vault.ingest()
    return {"ingested": [d.as_dict() for d in docs]}


@app.get("/api/probe/models")
async def probe() -> dict[str, Any]:
    return await probe_token_factory(settings)


@app.get("/", include_in_schema=False)
@app.get("/api/index", include_in_schema=False)
async def index():
    """Serve the UI.

    Two paths, for two good reasons. Locally it is `/`. On Vercel the rewrite
    that fronts the function delivers `/api/index` as the path (Vercel hands
    over the destination, not the original), so the UI has to answer there too.
    """
    page = WEB_DIR / "index.html"
    if page.exists():
        return FileResponse(page, media_type="text/html")
    return JSONResponse({"detail": f"UI not bundled (looked in {WEB_DIR})"}, status_code=500)
