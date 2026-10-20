# Architecture

## Request lifecycle

A single question can produce **two independent egress decisions**. That separation is deliberate:
the search query and the model prompt are different payloads with different risks.

```
POST /api/ask {question, doc_ids, consent}
   │
   ├─ 1. resolve scope        vault.get(doc_ids) → payload_sensitivity = max(doc.sensitivity)
   │
   ├─ 2. web leg (if the question asks about something current)
   │      outbound_query = question  (+ doc excerpt *only* if the question references them)
   │      classify_outbound(query)          → hard PII shapes only, not topics
   │      decide(sensitivity, {WEB})
   │        ├─ refused → ledger("refusal") → RETURN 403-shaped payload, stop
   │        └─ allowed → redact → Tavily → ledger("web")
   │
   ├─ 3. model leg
   │      capabilities = {VISION if any doc is an image,
   │                      LONG_CONTEXT if cross-doc language or >100k tokens}
   │      pre_redaction = scrub(all docs)          → residual_total
   │      decide(sensitivity, capabilities, consent, residual)
   │        ├─ refused → ledger("refusal") → RETURN, stop
   │        └─ allowed → build prompt (redacted iff tier is cloud and sens > personal)
   │                     provider.complete() → ledger("call")
   │
   └─ 4. return answer + decision + ledger sequence numbers
```

### Why the decision cannot live in the prompt

The guardrail must be enforced by something the model cannot argue with. `policy.decide()` is a
pure function of `(sensitivity, capabilities, consent, residual)` — no model in the loop, no
sampling, fully testable. The model never sees a policy; it sees an already-scrubbed payload.

### Why vision pins to the device

If the answer requires *seeing* a document, the document is the payload. You cannot de-identify a
scan by rewriting its text, because the text is in the pixels. So `VISION + sensitivity >= sensitive
→ LOCAL`, with `reason_code: vision_pinned_local`. This is the reason the local tier must be a
vision-language model (Bolt 74B-A9B) and not just a text model: otherwise ingestion itself leaks.

### Why the normaliser is order-sensitive

`redact.py` runs the most specific patterns first. A My Number (`1234 5678 9012`) would otherwise
be eaten by the phone pattern and emerge as a `«PHONE_1»` that nobody recognises as an identifier.
The residual check re-scans the scrubbed text for identifier shapes and reports a count; a nonzero
`residual_total` closes the cloud path even with consent.

---

## Tier contract

| Tier | Model | Egress | Vision | Cost /1M in·out | Chosen when |
|---|---|---|---|---|---|
| `local` | Nemotron 3.5 Lightning 30B-A3B (Ollama, MLX) | device | no* | $0 | default; always permitted |
| `tf_light` | Nemotron 3.5 Lightning 30B-A3B | cloud | no | $0.06 · $0.24 | routine permitted work |
| `tf_deep` | Nemotron 3 Ultra 550B-A55B | cloud | no | $1.00 · $3.00 | long-context recall required |

\* The vision tier is **Nemotron 3.5 Bolt 74B-A9B** — pulled separately and set via
`CONFIDANT_MODEL_LOCAL_VISION`. With Bolt present, `vision_pinned_local` becomes a real path
rather than a policy branch; without it, image documents are refused rather than sent to a
cloud VLM.

The router is **local-first**: among permitted tiers it picks the cheapest, so `tf_light` is only
reached when local is excluded or incapable. `tf_deep` is reached only for long-context work, where
it is the *only* capable permitted tier — never by default, never by accident.

Deliberately absent: **Nemotron 3 Super (120B, Mar 2026)**. Superseded at the same shape by
Nemotron 3.5 Super VL (higher capability index, ~4.5× throughput). If Super VL lands on Token
Factory it slots into the middle as a config change (`CONFIDANT_MODEL_LIGHT`), not a rewrite.

### Node Router is not used for routing

NVIDIA ships NeMo Switchyard, which routes between Nemotron sizes on cost and capability. Confidant
builds its own because its **first** constraint is data residency: the router must refuse to send a
document to the cloud *even when that would be cheaper and better*. A cost router cannot express
that. Switchyard is credited as prior art, not used.

---

## Deployment shape (and why it is not all on a GPU)

| Layer | Where | Cost |
|---|---|---|
| Policy engine, redactor, ledger, UI | any host | $0 |
| Local tier | the user's machine (Ollama) | $0 |
| Cloud tiers | Token Factory | per token |
| Nightly consolidation | Nebius AI Cloud **Serverless Job** | ~$0.39/run |

A 24/7 GPU endpoint on Nebius Cloud would cost roughly $37/day at published L40S rates
(~$1,674 across the 45-day period the submission must stay reachable). Jobs are finite and bill
per run, so the same work costs pennies. See `docs/FEEDBACK.md` — this is also feedback we gave
the sponsor.

### OpenShell: designed for, partially wired

NVIDIA OpenShell enforces policy **out of process** — a sandbox, a policy engine and a privacy
router that sit between the agent and the infrastructure, so a compromised or merely creative agent
cannot talk its way past them. That is the correct enforcement point for this product, and NemoClaw
already supports Hermes (`nemohermes onboard`).

Confidant's policy engine is intentionally **portable and application-level** today, so the product
runs anywhere (including a laptop with no Docker). The intended production shape is:

```
OpenShell sandbox
  └── Hermes Agent + confidant plugin   ← decisions still made here
  └── OpenShell privacy router          ← enforces egress at the boundary
```

The two layers agree by construction: Confidant never asks for an egress that OpenShell's policy
would deny. Moving enforcement down into OpenShell is a deployment change, not a design change —
which is exactly how it should be.

---

## Failure modes, and what each one does

| Failure | Behaviour |
|---|---|
| Token Factory unreachable | `completion` raises; the request fails closed. No silent local fallback that would change the answer's provenance. |
| Tavily unreachable | `web_meta.error` is recorded in the ledger; synthesis continues from documents only. The degraded leg is visible. |
| Ollama not running (live mode) | local tier errors rather than silently promoting to cloud — promotion would be an unprompted egress. |
| Truncated model output | `finish_reason` is stored on the completion and surfaced in `usage`, so a cut-off answer is distinguishable from a short one. |
| Ledger tampered | `/api/verify` reports `broken_at_seq`; the UI header flips from `verified` to `BROKEN`. |

---

## Test strategy

- `test_policy.py` — the promises, expressed as assertions (restricted never reaches cloud without
  consent + clean scrub; vision pins local; web + identifier refuses).
- `test_redact.py` — identifiers removed, residual zero, and *structure preserved*: two addresses
  in one payload become `«ADDRESS_1»` and `«ADDRESS_2»`.
- `test_ledger.py` — chain verifies; mutating a record and deleting a record are both detected at
  the exact sequence number.
- `test_router.py` — full ingest→answer path against the mock provider, including a spy that
  asserts no identifier ever appears in a cloud-bound prompt.
- `test_e2e.py` — spawns the real server and speaks HTTP. This exists because a unit test passed
  while `AskRequest` silently dropped the `consent` field; a schema seam is invisible from inside
  the process.

Run: `env -u PYTHONPATH ./.venv/bin/python -m pytest tests -q`
