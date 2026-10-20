"""HTTP surface. Deliberately small: the UI is one page and everything it needs
is on this API.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import policy
from .config import DATA_DIR, LEDGER_PATH, REPO_ROOT, settings
from .ledger import Ledger
from .providers import probe_token_factory
from .router import Confidant, Vault

WEB_DIR = REPO_ROOT / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not vault.docs():
        vault.ingest()
    yield


app = FastAPI(title="Confidant", version="0.1.0", docs_url="/api/docs", lifespan=lifespan)

ledger = Ledger(LEDGER_PATH)
vault = Vault(DATA_DIR / "samples", ledger)
confidant = Confidant(cfg=settings, ledger=ledger, vault=vault)


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
async def ask(req: AskRequest) -> JSONResponse:
    result = await confidant.ask(
        req.question, req.doc_ids, allow_web=req.allow_web, consent=req.consent
    )
    result["stats"] = confidant.stats()
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


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
