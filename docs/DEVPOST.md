# Devpost submission copy

Paste-ready. Fill the three `<PLACEHOLDERS>` before submitting.

---

## Project name

**Confidant**

## Tagline (≤ 140 chars)

A personal AI that can prove what it didn't send. Every document classified, every egress decided, every refusal logged.

## Track

**Personal AI**

## Description

### The problem

Everyone owns a folder of documents they will not paste into a chat box: medical records, immigration
paperwork, tax filings, salary, family matters. Assistants are genuinely useful over that material —
and unusable over it, because using them means handing the whole folder to someone else's server.

The usual answer is a promise. Confidant's answer is a receipt.

### What it does

Confidant reads your documents, builds persistent memory, and answers questions across them —
while a policy engine decides what is allowed to leave your machine, and a tamper-evident ledger
records every decision, including the refusals.

Three Nemotron models, three jobs:

- **Nemotron 3.5 Bolt 74B-A9B** (local, Ollama) — vision ingestion and private Q&A. It is a
  vision-language model, which is the load-bearing detail: reading a scan used to require a cloud
  VLM, so the leak happened at ingestion, before any routing existed to prevent it.
- **Nemotron 3.5 Lightning 30B-A3B** (Nebius Token Factory) — the execution layer.
- **Nemotron 3 Ultra 550B-A55B** (Nebius Token Factory) — escalation, for long-context recall and
  cross-document contradiction hunting.

### The idea worth stealing

De-identification is normally a trade-off: scrub the identifiers and you destroy the detail the
expensive model needed. Confidant makes the scrub **lossy about content and lossless about
structure**. Two addresses in one payload become `«ADDRESS_1»` and `«ADDRESS_2»` — so a cloud model
can still find that they disagree, while never learning what either one was.

In the demo: the local tier honestly declines to certify a cross-document comparison. With explicit
per-request consent, the same question escalates to Nemotron Ultra de-identified — and finds that
the residence card and the resident record disagree on the address, which for a foreign resident in
Japan is the most common reason a visa renewal gets sent back. The ledger shows Ultra received two
tokens, not two addresses.

### Safety as a first-class outcome

When a request cannot be made safe, it is refused, not quietly downgraded: asking the web about a
residence card number returns `refused_restricted_web`, written to the ledger with the same weight
as a successful call. Topics are not payloads — a question about visa fees is allowed; a question
carrying an ID is not.

### How it is built

- Policy engine as a pure function of `(sensitivity, capabilities, consent, residual)` — no model in
  the loop, 49 tests, auditable in ~200 lines.
- Hash-chained JSONL ledger; editing a past record breaks verification at exactly that sequence.
- Japanese-aware de-identification (在留カード番号, マイナンバー, 電話, 住所, 氏名) with a residual
  check that closes the cloud path if anything identifier-shaped survives.
- Hermes Agent as the harness (Nebius Token Factory is a first-class provider there).
- Tavily for live lookups — the only third-party egress, and it passes through the same gate.
- Runs in mock mode with zero credentials, so a judge can click through every beat without a key.

### Where Token Factory accelerated the work

It is the reason the escalation is affordable at all. The same 150k-token question costs $0.0094 on
Lightning and $0.1545 on Ultra — a 16× spread that only makes sense to manage if the cheap tier is
genuinely cheap and the expensive tier is genuinely better. One OpenAI-compatible endpoint serving
all three Nemotron sizes turns tier selection into a string, not an integration, which is what made
a policy-driven router feasible in the time available. Ledger costs are computed from the reported
token usage in each response, never estimated.

### Honest limitations

The demo vault is synthetic (shaped like the real documents, invented details). The classifier is
rule-based and deterministic — a learned classifier is the upgrade path, but a regex pass is what
you can run *before* any model loads. Redaction is best-effort and reports its own residual. The
cost figures in the UI come from a four-question scripted run, not a benchmark. OpenShell is the
intended enforcement substrate and is designed for, partially wired.

---

## Built with

`nvidia-nemotron` · `nemotron-3-ultra` · `nemotron-3-5-lightning` · `nemotron-3-5-bolt` ·
`nebius` · `nebius-token-factory` · `nebius-ai-cloud` · `tavily` · `hermes-agent` ·
`python` · `fastapi` · `ollama` · `openai-compatible-api`

## Links

- **Repo:** `<REPO_URL>`
- **Video:** `<YOUTUBE_URL>` *(must be Public, not Unlisted)*
- **Live demo:** `<DEMO_URL>` — must stay reachable and free until judging ends **Dec 15, 2026**

## Testing instructions

No credentials required.

```bash
git clone <REPO_URL> && cd confidant
./run.sh
# open http://127.0.0.1:8765
```

Mock mode is a complete demo: policy engine, redactor and ledger are real; only the model text is
canned. Four preset buttons on the ask bar walk the four beats (local, escalated, refused, allowed).

For live inference, `cp .env.example .env`, set `NEBIUS_API_KEY` and `TAVILY_API_KEY`, then
`CONFIDANT_MODE=live ./run.sh`. Run `PYTHONPATH=src ./.venv/bin/python scripts/probe_models.py`
first — model ids move.

Tests: `env -u PYTHONPATH ./.venv/bin/python -m pytest tests -q` (49 passing, including end-to-end
over real HTTP).

## New vs existing

**This project is new**, created entirely within the submission period. It uses Hermes Agent as an
upstream open-source harness (MIT-licensed dependency, not a fork of the submission), and
NVIDIA/Nebius APIs as services. All application code, policy design, redaction logic, ledger,
tests and UI in this repository were written for this hackathon.

---

## Pre-submit checklist

- [ ] Repo **public**, LICENSE visible in the GitHub **About** sidebar (not just a LICENSE file)
- [ ] `git ls-files | grep -iE '\.env$'` returns nothing
- [ ] Unauthenticated `curl -s -o /dev/null -w '%{http_code}' <repo-url>` → `200`
- [ ] Video **Public** on YouTube, under 3:00, shows the app running
- [ ] Track = **Personal AI**
- [ ] Feedback section completed (see `docs/FEEDBACK.md`)
- [ ] Demo URL live from a session-free browser
