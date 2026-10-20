# Demo script — 3 minutes, hard cap

Judges are not required to watch past 3:00. Every second below is budgeted.

**Setup before recording**

```bash
cd confidant
rm -f data/ledger.jsonl          # clean ledger, so the count climbing is legible
CONFIDANT_MODE=live ./run.sh     # live if credits allow; mock is a valid fallback
```

Browser at `http://127.0.0.1:8765`, window ~1440 wide, zoom 100%. Close every other tab.
Have the terminal visible behind the browser for the refusal beat's ledger line, or skip it.

---

## 0:00 – 0:20 — The claim

> "Every AI assistant asks you to trust it with your documents. This one produces a receipt.
>
> These are my real-life documents: my residence card, my resident record, a clinic note, my
> employment contract. A policy engine decides what may leave this machine, and a hash-chained
> ledger records every decision — including the ones it refuses."

Show the left pane. Point at the sensitivity chips: **restricted**, **restricted**, **restricted**,
**personal**, **public**.

> "Classified on-device, before any model was loaded."

⏱ Don't linger. The chips are context, not the demo.

---

## 0:20 – 1:00 — Beat 1: it stays home

Click preset **"Visa risk?"**

Expected: `tier: local` · `cost: $0.000000` · answer ends "Recommend: escalate."

> "Cross-document question. Policy says: these documents are restricted, so the local model —
> Nemotron 3.5 Lightning, running on this laptop through Ollama — handles it. Cost, zero.
>
> And notice what it does: it *declines* to answer. It can read four documents, but it will not
> certify a cross-document comparison it can't do reliably. That honesty is the feature — the
> alternative is a confident wrong answer about your visa."

---

## 1:00 – 1:50 — Beat 2: the escalation (the money shot)

Tick the consent box. Ask again (preset **"Visa risk?"**).

Expected: `tier: tf_deep` · `de-identified` chip · `$0.002069` · answer opens with
**ADDRESS MISMATCH**.

> "One tick — explicit, per-request consent to de-identified escalation. Now it goes to Nemotron 3
> Ultra on Nebius Token Factory. Two thousandths of a dollar.
>
> And it found the thing that actually matters: my residence card says 港区, my 住民票 says 渋谷区
> — I moved and never filed the 住居地届出. That's the single most common reason a renewal gets
> sent back."

**Then the reveal.** Scroll the ledger, point at the `redaction` line for `#7`:

> "Here's what Ultra actually received: `«ADDRESS_1»` and `«ADDRESS_2»`. It never saw either
> address. I gave it the *shape* of the contradiction and kept the content.
>
> That's the trick. Redaction usually destroys the thing the expensive model needed. This one
> destroys the content and keeps the structure."

If asked "how do you know it's not the same token?" — open `tests/test_redact.py` and show
`test_redaction_preserves_the_shape_of_a_contradiction`.

---

## 1:50 – 2:20 — Beat 3: the refusal

Click preset **"Identifiers to web"** (the red-tinted one).

Expected: `REFUSED` · `refused_restricted_web`.

> "Now the case where the right answer is no. Asking the web about a residence card number would
> put that number on someone else's server. Refused — and the refusal is in the ledger with the
> same weight as a successful call.
>
> A system that only logs what it did, and never what it declined to do, isn't an audit trail."

Then click **"Visa fee (web)"** to show the contrast:

> "Same feature, no identifier: allowed. The query that left was the topic, not the document."

---

## 2:20 – 2:50 — The ledger

Point at the right pane.

> "Hash-chained. Each record carries the hash of the one before it. Edit a past entry and
> verification breaks at exactly that sequence number."
>
> *(optional, 10s)* `curl -s localhost:8765/api/verify`

Stats line: `stayed home 61%` · `spent $0.0021` · `refused 1`.

> "Sixty-one percent of tokens never left the machine, and the one escalation cost a fifth of a
> cent."

---

## 2:50 – 3:00 — Close

> "Three Nemotron models, one family, three sizes — chosen by a policy that answers to data
> residency before price. Hermes Agent as the harness, Token Factory as the engine, Tavily through
> the same gate.
>
> Your data, provably yours. That's Confidant."

**Stop talking at 2:55.** Let it end clean.

---

## Fallbacks

| If | Then |
|---|---|
| Token Factory errors / credits gone | `CONFIDANT_MODE=mock`. Every beat above still plays, including the refusal. Say "running against the deterministic fallback" — do not pretend it's live. |
| Ollama not running | Mock mode. The local beat's answer is identical. |
| Tavily rate-limited | Beat 4 degrades to a ledger `error` field; skip the second half of beat 3 and keep moving. |
| Demo machine projects to a projector | Zoom 125%, and the three-pane layout still holds at 1280. |
| A judge asks for the numbers | They came from a four-question scripted run, not a benchmark. Say so. |

## Recording notes

- Record 1080p, one continuous take, no music (copyright), captions burned in if possible.
- Cut anything that isn't a beat. Three minutes is a constraint, not a target.
- Upload to YouTube as **Public** — unlisted does not satisfy the rules.
