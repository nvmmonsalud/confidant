# Feedback for Nebius / NVIDIA

The submission form requires feedback on Token Factory, AI Cloud and NVIDIA's models. It is also
its own prize category, judged on completeness, viability and impact — so this is written to be
useful rather than polite.

Fill in the `<…>` items with anything you hit that isn't listed.

---

## Nebius Token Factory

**What worked.** One OpenAI-compatible endpoint across the whole Nemotron family is the single
biggest ergonomic win of this hackathon. Switching tiers became a string, which is what made a
policy-driven router practical in the time available. Reported `usage` being accurate enough to bill
from directly meant the ledger's cost figures are measured, not estimated.

**Friction, in priority order.**

1. **Catalogue naming is inconsistent across surfaces.** The same model appears as
   `nvidia/Nemotron-3_5-Lightning` in some listings and `nvidia/nemotron-3.5-lightning-30b-a3b` in
   the model card, and `Nemotron-3-Ultra-550b-a55b` vs `nemotron-3-ultra-550b-a55b` elsewhere. For
   anyone writing a multi-tier router this is a real failure mode: a wrong id is only discovered at
   the first live call. Returning the canonical id from `GET /v1/models` alongside a human name, and
   using that id in docs, would remove a class of support tickets.

2. **The catalogue lags the model releases.** Nemotron 3.5 Super VL and Bolt 74B-A9B were
   announced and on Hugging Face, but not visible on Token Factory at build time. The obvious
   architecture — small/medium/large — was unavailable, so we shipped small/large and left a config
   seam for the middle tier. A "coming to Token Factory" row in the console would let builders plan
   around the gap instead of discovering it.

3. **Publishing latency data per model would change routing decisions.** We chose Ultra for
   long-context escalation because of published recall benchmarks, but we could not see
   time-to-first-token per model per region without measuring it ourselves. A `/v1/models` field for
   observed p50 latency over the last hour would let routers pick on measured behaviour.

4. **Documentation for *reasoning* token accounting.** Reasoning models bill hidden reasoning as
   output. A tight `max_tokens` truncates before the visible answer starts, and the failure looks
   like a bad answer rather than a truncation to anyone who doesn't check `finish_reason`. A single
   doc page with recommended caps per model family would prevent a lot of "the model is broken"
   reports.

## Nebius AI Cloud

1. **The $25 card verification is a hard charge, and it is disclosed as "verification".** The docs
   do say the $25 is added to the balance, but the in-product copy reads "Payment card required ·
   $25 verification", which reads like a hold. Several public complaints suggest others interpreted
   it the same way. Wording it as "we charge $25 and credit it to your balance" would remove the
   surprise entirely — and the trust cost of a surprise on a billing screen is disproportionate.

2. **Budgets do not cap spending.** The docs are commendably explicit — *"A budget does not stop or
   cap your usage"* — but the feature name still implies a limit. For a hackathon user running an
   agent that can create resources unattended, email alerts that update every few hours are not a
   safety net. A hard spend ceiling per project (even a coarse one) would make it safe to leave
   something running overnight, which is precisely the always-on use case the Personal AI track
   asks for.

3. **Serverless Endpoints are persistent, not scale-to-zero.** This is documented, but it is
   surprising given the "Serverless" name, and it changes the architecture: a 24/7 GPU endpoint at
   published L40S rates is roughly $37/day, which is ~$1,674 over the 45-day window a hackathon
   submission must remain reachable. Serverless **Jobs** were the right primitive and cost ~$0.39
   per run. A one-line comparison table at the top of the Serverless docs — "endpoints bill while
   running; jobs bill per run" — would save builders a bad first design.

4. **No Asia region at build time.** `eu-north1` / `us-central1` / `us-north1` put ~120–250 ms
   between a Tokyo user and their inference. Irrelevant for batch work, noticeable for interactive
   assistants. Worth stating in the latency docs so builders can decide before they architect.

## NVIDIA models

**What worked.** The Nemotron 3.5 family's efficiency story is real and it is the reason this
architecture is possible: a 3B-active model that can run a private tier on a laptop, and a 550B MoE
that can be escalated to for a sixteenth of a cent per question.

1. **Publish a migration table between generations.** Nemotron 3 Super (120B, Mar 2026) and
   Nemotron 3.5 Super VL (120B, Oct 2026) are the same shape and both are live in catalogues, but
   the newer one is substantially stronger and faster. Nothing in the model card says "prefer this
   one". Anyone who picked Super from a six-month-old blog post is running the weakest model in the
   family without knowing it. A "supersedes / superseded by" field on the model card would fix this
   at essentially zero cost.

2. **State active-vs-total parameters in the first line of every listing.** Pricing tracks *active*
   parameters, not total, so a 550B MoE costs 16× a 30B MoE, not 18×… which happens to be
   coincidentally similar here but is not a rule users can rely on. Making `A55B` / `A3B` the
   headline number in catalogue listings — not just in the model card — would make cost predictable
   from the listing page.

3. **Vision on small models is a bigger deal than the benchmark table suggests.** Bolt 74B-A9B
   being a vision-language model at a 24 GB footprint is what let us keep document ingestion
   on-device. The model card leads with coding and tool use; the document-intelligence use case is
   the one that unlocks privacy-preserving assistants, and it deserves a headline.

4. **NemoClaw + Hermes is an excellent story that is hard to find.** The fact that `nemohermes` exists
   — a supported, one-command path to running Hermes inside OpenShell — is buried in the NemoClaw
   docs. It is the fastest way to demonstrate out-of-process policy enforcement to a builder who
   already runs Hermes. A "if you run Hermes, start here" link on the NemoClaw README would have
   saved us a research pass.

## One suggestion for the track itself

The Personal AI track asks for "an always-on, private assistant that keeps your data under your
control." Almost any submission can *claim* that. Consider asking entrants for one artefact that
cannot be faked: a log of a refusal. A system that never declines anything has no boundary to show.
