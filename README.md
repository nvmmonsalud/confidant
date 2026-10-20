# Confidant

**A personal AI that can prove what it didn't send.**

Your residence card, your clinic note, your contract, your bank balance — the documents you
would never paste into a chat box. Confidant reads them, remembers them, and answers questions
across them, while a policy engine decides what is allowed to leave your machine and a
tamper-evident ledger records every decision it made.

Built for the **Nebius × NVIDIA Global AI Hackathon — Personal AI Track**.
Runs on **NVIDIA Nemotron** models via **Nebius Token Factory**, with local inference on
**Nemotron 3.5 Bolt** and live lookups through **Tavily**.

---

## The 20 seconds that matter

Most "privacy-first AI" demos ask you to trust a promise. This one produces a receipt.

```
ask:  "Does anything across my documents put my visa renewal at risk?"

  default posture  →  tier: local (on-device)      cost: $0.000000
                      "comparing facts across four documents reliably is past
                       what I should answer alone. Recommend: escalate."

  you tick consent →  tier: tf_deep (Nemotron Ultra)  cost: $0.002069
                      "ADDRESS MISMATCH — your 在留カード lists 港区芝浦4丁目2番8号,
                       but the 住民票 issued after your November 2025 move lists
                       渋谷区道玄坂1丁目5番3号. The 住居地届出 was never filed."

                      ledger: what the cloud model actually received was
                      «ADDRESS_1» vs «ADDRESS_2» — never the addresses themselves.
```

The escalation is the point. **The cloud model compared two tokens; the mismatch survived, the
content did not.** That is the trick that makes de-identified reasoning useful instead of
useless, and it is why redaction cannot be a lossy bag of `[REDACTED]`.

And when a request cannot be made safe at all:

```
ask:  "What is the current rule for residence card AB12345678CD?"

      REFUSED   reason_code: refused_restricted_web
      "a web search would transmit restricted content to a third party."
```

The refusal is written to the ledger with the same weight as a successful call. A system that
only logs what it did, never what it declined to do, is not an audit trail.

---

## How it works

```
                    ┌──────────────────────────────────────────┐
  documents ───────▶│  classify on-device                      │
  (txt/pdf/img)     │  keyword + PII-shape rules, no model      │
                    │  → public / personal / sensitive / restricted │
                    └───────────────┬──────────────────────────┘
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │  policy.decide()                         │
                    │  1. data residency before cost           │
                    │  2. capability second (vision, recall)   │
                    │  3. cheapest permitted tier third        │
                    └───────────────┬──────────────────────────┘
                    ┌───────────────┼──────────────────────────┐
                    ▼               ▼                          ▼
              ┌──────────┐   ┌─────────────┐            ┌─────────────┐
              │  LOCAL   │   │ TF_LIGHT    │            │  TF_DEEP    │
              │ Bolt 74B │   │ Lightning   │            │ Ultra 550B  │
              │ no egress│   │ 3.5, 30B-A3B│            │ 550B-A55B   │
              └──────────┘   └─────────────┘            └─────────────┘
                    └───────────────┴──────────────────────────┘
                                    ▼
                    ┌──────────────────────────────────────────┐
                    │  hash-chained ledger (JSONL)             │
                    │  every decision, refusal and ingest      │
                    └──────────────────────────────────────────┘
```

### The policy, in one table

| Sensitivity | Local | Token Factory (raw) | Token Factory (de-identified) |
|---|---|---|---|
| public | ✅ | ✅ | n/a |
| personal | ✅ | ✅ | n/a |
| sensitive | ✅ | ❌ | ✅ |
| restricted | ✅ | ❌ | ✅ **only** with explicit consent **and** a zero-residual scrub |

Three properties worth calling out, because they are the whole design:

1. **Topics are not payloads.** "What is the fee for a 技人国 visa?" mentions immigration and
   carries nothing personal — it must not be refused. "Look up AB12345678CD" carries an
   identifier and must be. So outbound strings are classified on *hard PII shapes only*
   (`classifier.classify_outbound`), never on keywords.
2. **Vision pins to the device.** If a document has to be *seen* (a scan, a photo, a PDF), and it
   is sensitive, there is no cloud path — the pixels are the payload. Redaction cannot help.
3. **A refusal is a first-class outcome.** `refused_restricted_web`, `refused_no_redactor`,
   `refused_no_permitted_tier`. No silent downgrade, no "we did it anyway but cheaper".

Read `src/confidant/policy.py` — it is ~200 lines and a judge can verify every claim above
without running anything.

### The ledger

`data/ledger.jsonl`, append-only, one line per event, each record carrying
`sha256(prev_hash + payload)`. `GET /api/verify` walks the chain. Editing a past entry breaks it
at exactly that sequence number — there is a test for that (`test_ledger.py::test_tampering_...`).

What goes in a record: task id, question, document ids, sensitivity, chosen tier, model, egress
(`device`/`cloud`), reason code, redaction counts **and residual count**, tokens, cost, latency,
and the hash. What never goes in: the redaction *mapping*. Originals stay in process memory so
the UI can re-hydrate a token; they are never written down.

---

## NVIDIA models used, and why each one

This is not "we called a model". Three models, three different jobs, chosen for reasons that
survive a follow-up question.

| Model | Role | Why this one |
|---|---|---|
| **Nemotron 3.5 Lightning 30B-A3B** | Local tier (Ollama/MLX) + execution layer on Token Factory | The device tier today: 3B active, runs on this laptop, $0, and it reads Japanese paperwork correctly (measured 8s for a clinic-note summary). The same model on Token Factory handles routine cloud work at $0.06/$0.24 per 1M. |
| **Nemotron 3.5 Bolt 74B-A9B** | Vision upgrade for the local tier | 9B active out of 74B, fits a 24 GB / 32 GB recipe, and it is a **vision-language** model. That is the load-bearing detail for scanned documents: before this, reading a scan required a cloud VLM, so the leak happened at *ingestion*, before any routing existed to prevent it. Set `CONFIDANT_MODEL_LOCAL_VISION` once pulled. |
| **Nemotron 3 Ultra 550B-A55B** | Escalation on Token Factory | The only tier that wins on long-context recall and numeric precision — which is exactly what cross-document contradiction hunting is. 16× the price of Lightning, so it is entered deliberately, never by default. |

**A note on what we deliberately did *not* use: Nemotron 3 Super (120B, March 2026).** At the
same 120B/12B shape it has been superseded by Nemotron 3.5 Super VL, which scores substantially
higher on independent capability indices at ~4.5× the throughput. Building a tidy
Lightning → Super → Ultra ladder would have made the middle tier the weakest model in the stack.
So the ladder is two cloud tiers plus a local one. *Verify current model ids with
`scripts/probe_models.py` before quoting any of this.*

### Where Token Factory earned its place

- It is the **only reason the escalation is affordable**: the same 150k-token question costs
  $0.0094 on Lightning and $0.1545 on Ultra. A router only makes sense if the cheap tier is
  genuinely cheap and genuinely capable.
- It exposes **all three Nemotron sizes behind one OpenAI-compatible endpoint**, so switching
  tiers is a string, not an integration.
- Ledger costs are computed from **reported token usage in the response**, not estimated — every
  dollar figure in the UI came from `usage.prompt_tokens` / `completion_tokens`.

### Nebius tools used

| Tool | Use |
|---|---|
| **Token Factory** | All cloud inference (Lightning + Ultra). Native OpenAI-compatible; Hermes Agent has a first-class `nebius-token-factory` provider, so wiring is one env var. |
| **Nebius AI Cloud (Serverless Job)** | Nightly consolidation — memory compaction and a policy-eval sweep. Finite, billed per run (~$0.39/night at published L40S rates), because a 24/7 GPU endpoint would cost ~$37/day and the model must stay reachable until judging ends. *(Wired as a deployment step; see `docs/ARCHITECTURE.md`.)* |
| **Tavily** | Live lookups — the only third-party egress in the system, and it goes through the same redaction gate as everything else. |

---

## Judging criteria, addressed directly

**Technological Implementation.** A real policy engine, not a prompt asking the model to behave.
Out-of-process decisions made *before* the model is loaded; sensitivity attached to the payload
rather than the user; two independent decisions per request (the web leg and the model leg); a
hash-chained ledger with tamper detection; JP-aware de-identification that preserves the *shape*
of a cross-document contradiction while removing its content. 49 tests, including an end-to-end
suite that spawns the server and speaks HTTP, because a unit test once passed while the HTTP
layer silently dropped a consent flag.

**Design.** A complete product surface, not a CLI: three-pane UI (vault / thread / live ledger),
sensitivity chips per document, a consent control that appears only when a request actually needs
escalation, and a ledger that reads like a flight recorder. Runs in mock mode with zero
credentials, so a judge can click through every beat without a key or a credit.

**Potential Impact.** Every person owns a folder of documents they will not paste into ChatGPT:
medical records, immigration paperwork, tax filings, salary, family matters. That is not a niche —
and for foreign residents in Japan the paperwork is a recurring, high-stakes, low-support chore
that an assistant can genuinely help with *only if* it can be trusted with the source. Confidant
addresses a real workflow, with the demo built on the kind of documents its author actually has.

**Quality of the Idea.** The non-obvious move is that de-identification is *lossy about content
and lossless about structure*. Redact two addresses and you lose the addresses but keep the
`«ADDRESS_1» ≠ «ADDRESS_2»` signal — which is exactly what the expensive model needs in order to
find the contradiction. Privacy and capability stop being a trade-off and become the same
mechanism.

---

## Quickstart

```bash
git clone <repo> && cd confidant
./run.sh                      # mock mode: no keys, no network, no cost
# → http://127.0.0.1:8765
```

Mock mode is a full product demo: the policy engine, redactor and ledger are real, and only the
model text is canned. Click **Visa risk?**, then tick the consent box and ask again.

### Live mode

```bash
cp .env.example .env          # then fill in NEBIUS_API_KEY and TAVILY_API_KEY
CONFIDANT_MODE=live ./run.sh
```

Before trusting any model id:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/probe_models.py
```

### Three modes

| Mode | Device tier | Cloud tiers | Used for |
|---|---|---|---|
| `mock` | canned | canned | tests, offline demo, zero credentials |
| `hybrid` | **labelled stand-in** (`…:stand-in` in the ledger) | **real** Token Factory | the deployed demo — a server has no laptop to be private on, so it says so instead of pretending |
| `live` | real Ollama on your machine | real Token Factory | recording the video, real use |

The `hybrid` stand-in is deliberate: serving the device tier from the cloud on the public demo
would invert the entire claim. The ledger records `:stand-in` so nobody has to take it on trust.

### Deployed demo

Hosted on Vercel as a single Python function (`api/index.py` + `vercel.json`), with the ledger
redirected to `/tmp` because the rest of the filesystem is read-only. Guardrails keep a public,
unauthenticated URL from spending real money:

- `CONFIDANT_PER_IP_COOLDOWN` — seconds between live calls per IP (default 5)
- `CONFIDANT_DAILY_CAP` — hard ceiling on live calls per UTC day (default 300)

Both surface in the UI as a visible counter. At Ultra's published rate, a fully exhausted day is
well under a dollar.

Config: `CONFIDANT_MODEL_LIGHT`, `CONFIDANT_MODEL_DEEP`, `CONFIDANT_MODEL_LOCAL`,
`CONFIDANT_OLLAMA_BASE_URL`, `CONFIDANT_NEBIUS_BASE_URL`, `CONFIDANT_MODE`,
`CONFIDANT_LOCAL_THINK`, `CONFIDANT_TIMEOUT`. All documented in `.env.example`.

### Tests

```bash
env -u PYTHONPATH ./.venv/bin/python -m pytest tests -q
```

`env -u PYTHONPATH` matters: Hermes exports a `PYTHONPATH` pointing at its own venv, which makes
a missing dependency look installed until the first import fails.

---

## What is honest about this build

- **The demo vault is synthetic.** The documents are invented — but they are shaped like the real
  thing (在留カード, 住民票, 診療記録, 雇用契約書), and the planted contradiction between the card and
  the resident record is a genuinely common renewal problem in Japan.
- **The classifier is rule-based.** Deterministic, auditable, no sampling tail. A learned
  classifier (Bolt E4B) is the upgrade path; a regex pass is the thing you can run *before* any
  model is loaded, which is the order that matters.
- **Redaction is best-effort and says so.** Every decision records a `residual_total`; a scrub
  with residual PII does not buy egress. That is why `restricted` is not "safe if redacted" by
  default — it needs an explicit, per-request, ledger-recorded consent.
- **The numbers in the UI come from a four-question scripted run**, not a benchmark. The
  cost-per-token figures are published Token Factory rates; confirm them against your own console.
- **OpenShell is the intended enforcement substrate.** The policy engine here is application-level
  and portable; wrapping the Hermes process in NVIDIA OpenShell moves enforcement out of the
  agent's reach entirely. Designed for, partially wired — see `docs/ARCHITECTURE.md`.

## Layout

```
src/confidant/
  policy.py       the rules — start here
  redact.py       JP-aware de-identification + residual check
  classifier.py   sensitivity, on-device, deterministic
  ledger.py       hash-chained audit trail
  router.py       classify → decide → scrub → call → record
  providers.py    Ollama · Token Factory · Tavily · mock
  api.py          HTTP surface
web/index.html    the whole UI, one file, no build step
tests/            49 tests, including end-to-end over real HTTP
docs/             architecture · demo script · Devpost copy · feedback
```

## License

MIT. See `LICENSE`.
