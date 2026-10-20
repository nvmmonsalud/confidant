"""The orchestrator: classify -> decide -> (redact) -> call -> record.

Design rule that everything else follows: **sensitivity attaches to the
payload, not to the user.** A question about visa fees is public; the same
question asked "based on my residence card" is restricted. So each egress
event — the web lookup, the model call — gets its own independent decision and
its own ledger line.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import classifier, policy, redact
from .config import Settings, cost_usd, settings as default_settings
from .ledger import Ledger, Record
from .policy import Capability, Decision, Sensitivity, Tier, max_sensitivity
from .providers import Completion, Provider, TavilyClient, build_provider, est_tokens

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".heic"}

_WEB_INTENT = re.compile(
    r"\b(current|latest|today|this year|fee|fees|rule|rules|law|deadline|news)\b"
    r"|最新|現在|今年|手数料|料金|制度|改正|締切|期限について",
    re.IGNORECASE,
)
_CROSS_DOC = re.compile(
    r"\b(across|all my documents|everything|contradict\w*|inconsisten\w*|risk)\b"
    r"|矛盾|全部|すべて|食い違",
    re.IGNORECASE,
)
_REFERENCES_DOCS = re.compile(
    r"\b(my documents?|my card|my record|my contract|my note|according to my|based on my)\b"
    r"|私の|自分の|書類|カード",
    re.IGNORECASE,
)

DEFAULT_SYSTEM = (
    "You are Confidant, a personal assistant running on hardware the user owns. "
    "Answer only from the sources provided in this prompt. If the sources do not "
    "support an answer, say so plainly and name what is missing. Never invent a "
    "date, a number, or an address. Cite the document ids you used."
)


@dataclass
class Doc:
    id: str
    title: str
    text: str
    path: str
    sensitivity: Sensitivity = Sensitivity.PUBLIC
    signals: list[str] = field(default_factory=list)
    is_image: bool = False
    tokens: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "sensitivity": self.sensitivity.value,
            "signals": self.signals,
            "is_image": self.is_image,
            "tokens": self.tokens,
            "preview": self.text.strip().splitlines()[0][:90] if self.text.strip() else "",
        }


class Vault:
    """Document store. Ingestion classifies; classification never leaves."""

    def __init__(self, root: Path, ledger: Ledger | None = None) -> None:
        self.root = Path(root)
        self.ledger = ledger
        self._docs: dict[str, Doc] = {}

    def ingest(self) -> list[Doc]:
        if not self.root.exists():
            return []
        found: list[Doc] = []
        for path in sorted(self.root.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            is_image = path.suffix.lower() in _IMAGE_SUFFIXES
            text = "" if is_image else path.read_text(encoding="utf-8", errors="replace")
            cls = classifier.classify(text, title=path.stem)
            doc = Doc(
                id=path.stem,
                title=path.stem.replace("_", " ").title(),
                text=text,
                path=str(path),
                sensitivity=cls.sensitivity,
                signals=cls.signals,
                is_image=is_image,
                tokens=est_tokens(text),
            )
            self._docs[doc.id] = doc
            found.append(doc)
            if self.ledger is not None:
                self.ledger.append(
                    self.ledger.new_record(
                        task_id=f"ingest-{doc.id}",
                        kind="ingest",
                        doc_ids=[doc.id],
                        sensitivity=doc.sensitivity.value,
                        reason_code="classified_on_device",
                        reason=f"{len(cls.signals)} signals, never left the device",
                        egress="device",
                    )
                )
        return found

    def docs(self) -> list[Doc]:
        return list(self._docs.values())

    def get(self, ids: list[str] | None) -> list[Doc]:
        if not ids:
            return self.docs()
        return [self._docs[i] for i in ids if i in self._docs]


class Confidant:
    def __init__(
        self,
        cfg: Settings | None = None,
        ledger: Ledger | None = None,
        vault: Vault | None = None,
    ) -> None:
        self.cfg = cfg or default_settings
        self.ledger = ledger or Ledger(Path(__file__).resolve().parents[2] / "data" / "ledger.jsonl")
        self.vault = vault or Vault(Path(__file__).resolve().parents[2] / "data" / "samples", self.ledger)
        self.redactor = redact.Redactor()
        self.tavily = TavilyClient(self.cfg)

    # -- main entry point -------------------------------------------------
    async def ask(
        self,
        question: str,
        doc_ids: list[str] | None = None,
        *,
        allow_web: bool = True,
        consent: bool = False,
    ) -> dict[str, Any]:
        task_id = uuid.uuid4().hex[:12]
        docs = self.vault.get(doc_ids)
        payload_sensitivity = max_sensitivity([d.sensitivity for d in docs]) if docs else Sensitivity.PUBLIC
        records: list[Record] = []

        # ---- stage 1: the web leg, if the question needs the outside world
        web_context = ""
        web_meta: dict[str, Any] | None = None
        if allow_web and _WEB_INTENT.search(question):
            query = self._outbound_query(question, docs)
            q_cls = classifier.classify_outbound(query)
            q_decision = policy.decide(q_cls.sensitivity, capabilities={Capability.WEB})
            if not q_decision.permitted:
                rec = self.ledger.append(
                    self.ledger.new_record(
                        task_id=task_id,
                        kind="refusal",
                        question=question,
                        doc_ids=[d.id for d in docs],
                        sensitivity=q_cls.sensitivity.value,
                        permitted=False,
                        reason_code=q_decision.reason_code,
                        reason=q_decision.reason,
                        egress="cloud",
                    )
                )
                records.append(rec)
                return self._refusal_payload(task_id, question, q_decision, records, stage="web")
            q_red = self.redactor.redact(query)
            web_meta = {"query_sent": q_red.text, "redaction": q_red.as_dict()}
            if self.cfg.live and self.cfg.tavily_api_key:
                try:
                    result = await self.tavily.search(q_red.text)
                    web_context = self._format_web(result)
                    web_meta["results"] = [
                        {"title": r.get("title"), "url": r.get("url")} for r in result.get("results", [])
                    ]
                except Exception as exc:
                    web_meta["error"] = str(exc)
            records.append(
                self.ledger.append(
                    self.ledger.new_record(
                        task_id=task_id,
                        kind="web",
                        question=question,
                        doc_ids=[d.id for d in docs],
                        sensitivity=q_decision.sensitivity.value,
                        tier="tavily",
                        model="tavily/search",
                        egress="cloud",
                        permitted=True,
                        reason_code="deidentified_query",
                        reason=q_decision.reason,
                        redaction=q_red.as_dict(),
                    )
                )
            )

        # ---- stage 2: decide where the synthesis happens
        capabilities: set[Capability] = set()
        if docs and any(d.is_image for d in docs):
            capabilities.add(Capability.VISION)
        if _CROSS_DOC.search(question) or sum(d.tokens for d in docs) > 100_000:
            capabilities.add(Capability.LONG_CONTEXT)

        # The decision must see how clean a scrub we can actually produce: a
        # redaction with residual PII is not a licence to egress.
        pre_redaction = self.redactor.redact("\n".join(d.text for d in docs))

        decision = policy.decide(
            payload_sensitivity,
            capabilities=capabilities,
            consent=consent,
            residual=pre_redaction.residual_total,
        )

        if not decision.permitted:
            rec = self.ledger.append(
                self.ledger.new_record(
                    task_id=task_id,
                    kind="refusal",
                    question=question,
                    doc_ids=[d.id for d in docs],
                    sensitivity=payload_sensitivity.value,
                    permitted=False,
                    reason_code=decision.reason_code,
                    reason=decision.reason,
                    egress="cloud",
                )
            )
            records.append(rec)
            return self._refusal_payload(task_id, question, decision, records, stage="model")

        # ---- stage 3: build the payload (redacting if the tier requires it)
        prompt, redaction_info = self._build_prompt(question, docs, web_context, decision)
        provider = build_provider(decision.tier.value.replace("tf_", ""), self.cfg)
        completion = await provider.complete(DEFAULT_SYSTEM, prompt)

        cost = cost_usd(
            policy.TIERS[decision.tier].price_key,
            completion.tokens_in,
            completion.tokens_out,
        )
        rec = self.ledger.append(
            self.ledger.new_record(
                task_id=task_id,
                kind="call",
                question=question,
                doc_ids=[d.id for d in docs],
                sensitivity=payload_sensitivity.value,
                tier=decision.tier.value,
                model=completion.model,
                egress=policy.TIERS[decision.tier].egress.value,
                permitted=True,
                reason_code=decision.reason_code,
                reason=decision.reason,
                redaction=redaction_info,
                tokens_in=completion.tokens_in,
                tokens_out=completion.tokens_out,
                cost_usd=cost,
                latency_ms=completion.latency_ms,
            )
        )
        records.append(rec)

        return {
            "task_id": task_id,
            "question": question,
            "refused": False,
            "answer": completion.text,
            "decision": decision.as_dict(),
            "tier_label": policy.TIERS[decision.tier].label,
            "model": completion.model,
            "mode": self.cfg.mode,
            "web": web_meta,
            "usage": {
                "tokens_in": completion.tokens_in,
                "tokens_out": completion.tokens_out,
                "cost_usd": cost,
                "latency_ms": completion.latency_ms,
                "finish_reason": completion.finish_reason,
            },
            "ledger_seqs": [r.seq for r in records],
        }

    # -- helpers ----------------------------------------------------------
    def _outbound_query(self, question: str, docs: list[Doc]) -> str:
        """What would actually leave the building for a web lookup.

        If the user asked about their own documents, the outbound query carries
        document content — which is what makes it restrictable. A generic
        question about visa fees carries nothing personal.
        """
        if _REFERENCES_DOCS.search(question) and docs:
            top = docs[0]
            return f"{question}\n\n[context] {top.text[:400]}"
        return question

    def _build_prompt(
        self,
        question: str,
        docs: list[Doc],
        web_context: str,
        decision: Decision,
    ) -> tuple[str, dict[str, Any]]:
        blocks: list[str] = []
        redaction_info: dict[str, Any] = {}
        for doc in docs:
            body = doc.text
            note = ""
            if decision.redaction_required and decision.tier is not Tier.LOCAL:
                red = self.redactor.redact(body)
                body = red.text
                note = f" (de-identified: {red.total} spans)"
                redaction_info = red.as_dict()
            elif decision.tier is not Tier.LOCAL and doc.sensitivity is Sensitivity.RESTRICTED:
                # Should be unreachable — policy forbids it — but belt and braces.
                raise RuntimeError("refusing to serialise restricted content to a cloud tier")
            blocks.append(f"<document id=\"{doc.id}\">{body}{note}</document>")
        if web_context:
            blocks.append(f"<web_results>{web_context}</web_results>")
        sources = "\n\n".join(blocks) if blocks else "<document id=\"none\">(no documents)</document>"
        return f"{sources}\n\nQuestion: {question}", redaction_info

    @staticmethod
    def _format_web(result: dict[str, Any]) -> str:
        lines = []
        if result.get("answer"):
            lines.append(f"answer: {result['answer']}")
        for item in result.get("results", [])[:3]:
            lines.append(f"- {item.get('title')}: {str(item.get('content', ''))[:300]}")
        return "\n".join(lines) or "(no results)"

    @staticmethod
    def _refusal_payload(
        task_id: str,
        question: str,
        decision: Decision,
        records: list[Record],
        *,
        stage: str,
    ) -> dict[str, Any]:
        return {
            "task_id": task_id,
            "question": question,
            "refused": True,
            "stage": stage,
            "answer": decision.reason,
            "decision": decision.as_dict(),
            "tier_label": "—",
            "model": None,
            "web": None,
            "usage": {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "latency_ms": 0},
            "ledger_seqs": [r.seq for r in records],
        }

    # -- read-side --------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        return self.ledger.stats()

    def verify(self) -> dict[str, Any]:
        return self.ledger.verify()
