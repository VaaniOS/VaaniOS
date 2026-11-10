# VaaniOS

**Speak it. Structure it. Execute.**

> Turn messy Hinglish voice instructions into safe, structured business actions.

```text
🎙️ Voice → 🧠 Intent → 🏢 Business Context → 🛡️ Validation → 👤 Approval → ⚡ Execution → 🔍 Verification
```

Built for the **Gnani AI Great Indian AI Internship Challenge**. It focuses on Indian SME
workflows, where business instructions often arrive as natural, code-switched voice
messages.

![Python 3.12](https://img.shields.io/badge/python-3.12-blue)

> [!IMPORTANT]
> **Current status:** VaaniOS runs the complete voice-to-business-action loop over
> deterministic, synthetic, in-memory business data. Both UNDERSTAND and ACT are
> implemented and tested. This is a prototype, not a production system: production
> integrations, persistent storage and production identity management are future work.

| Layer | Status |
|---|---|
| **UNDERSTAND**: audio, ASR, semantic compilation, input evaluation | ✅ Implemented |
| **ACT**: business context, validation, risk/policy, planning | ✅ Implemented (synthetic data) |
| Confirmation, approval, idempotent execution, UNKNOWN handling | ✅ Implemented |
| Read-back verification, audit trail, traces, evaluation sandbox | ✅ Implemented |
| HTTP API (FastAPI) with bearer-token authentication and role-based permissions | ✅ Implemented on every run route; search and sandbox routes are open (see [Route authentication boundary](#route-authentication-boundary)) |
| Production integrations: ERP, WhatsApp, telephony, TTS, persistent storage, identity provider | 🔜 Future |

The Python package is called `vaaniflow` (the project's working name in the design
documents is *VaaniFlow*).

---

## Table of contents

- [The problem](#the-problem)
- [The solution](#the-solution)
- [Demo](#-demo)
- [Why VaaniOS](#why-vaanios)
- [Safety by design](#safety-by-design)
- [Architecture](#architecture)
- [What the prototype demonstrates](#what-the-prototype-demonstrates)
- **Technical reference**
  - [What UNDERSTAND produces](#what-understand-produces)
  - [Example: the canonical voice note](#example-the-canonical-voice-note)
  - [Safety behaviour of the semantic layer](#safety-behaviour-of-the-semantic-layer)
  - [Getting started](#getting-started)
  - [Using the pipeline](#using-the-pipeline)
  - [Gnani speech-to-text integration](#gnani-speech-to-text-integration)
  - [Testing](#testing)
  - [Quality checks](#quality-checks)
  - [Repository structure](#repository-structure)
  - [Developer workflow](#developer-workflow)
  - [Current status](#current-status)
  - [Design principles](#design-principles)
  - [Known limitations](#known-limitations)
  - [Documentation map](#documentation-map)
  - [Contributing](#contributing)
  - [License](#license)

---

## The problem

In many Indian SMEs a business instruction is not an API request. It is a voice note
recorded on a noisy shop floor. A cement and steel wholesaler in Peenya sends his
assistant an 8-second WhatsApp message:

> *"Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. Rate
> wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. Invoice bana
> ke mujhe WhatsApp pe approve karne bhej do."*

That one sentence contains:

- **Code-switching**: Hindi grammar with English business vocabulary.
- **Spoken numbers**: "chaar sau bees" is 420.
- **Names, not identifiers**: "Sharma Builders" may match more than one customer;
  "Ultratech cement" may match more than one SKU.
- **A relative reference**: "the rate I told you *parso*" (the day before yesterday)
  only means something once it is checked against the business's quote history.
- **Several actions**: dispatch, invoice draft, notification and owner approval.
- **Urgency** ("turant") and **implicit context**: the delivery address, the stock and
  the tax rule are never spoken.

Getting the words right is only the first step. **The hard problem isn't
transcription. It's safely turning speech into business state.** A transcription error
or a guessed customer becomes a wrong dispatch, a wrong invoice or a wrong price.

---

## The solution

VaaniOS treats every voice instruction as untrusted input. It compiles the instruction
into typed state, grounds that state in business records, and lets only a validated,
approved and verified plan change anything.

```text
Voice
  ↓
Audio preprocessing                (format normalisation, measured quality)
  ↓
ASR                                (Gnani adapter · mock adapter for tests)
  ↓
Semantic compiler                  (deterministic, rule-based)
  ↓
Typed SemanticState + input evaluation
  ↓  ── handoff boundary: UnderstandResult ──
Business context resolution        (customer · product · quote · stock · tax · date)
  ↓
Validation + risk / policy         (deterministic, no LLM decides execution)
  ↓
Plan                               (requested − negated actions, duplicate check)
  ↓
Confirmation / approval / clarification / human handoff
  ↓
Execution                          (idempotency keys, UNKNOWN handling)
  ↓
Read-back verification
  ↓
Audit / trace
```

The core trust boundary:

> **Raw speech never directly becomes an irreversible business action.**
>
> The semantic layer interprets language. Business systems provide business truth.
> Deterministic validation and policy control execution.

---

## 🎬 Demo

### 1. Speech becomes typed state (UNDERSTAND)

The voice note above compiles to this state. It is a golden test
([`test_compiler.py`](apps/api/tests/unit/semantic/test_compiler.py)).

```text
intent:       CREATE_DISPATCH_ORDER
customer:     "Sharma Builders"         (a name, not a customer ID)
addressee:    "Suresh"
item:         "Ultratech cement"        (not a SKU)
quantity:     200 bag
price:        ₹420 / bag                (a spoken claim, still to be checked)
price_ref:    "Rate wahi …" anchored to "parso" → DAY_OFFSET:-2, PAST
tax:          GST exclusive             (the instruction only, no rate or amount)
urgency:      HIGH                      ("turant")

actions:
  DISPATCH
  CREATE_INVOICE_DRAFT
  SEND_NOTIFICATION                     (to the speaker, WhatsApp)
  REQUEST_APPROVAL                      (by the speaker)

actionability: PARTIAL                  ("Rate wahi" and "parso" need business context)
```

### 2. State is grounded in business data (ACT)

Running the same note through ACT on the synthetic dataset gives the following trace.
The business clock is the dataset's 2026-10-17, Asia/Kolkata.

```text
UNDERSTAND                 PARTIAL: references must be resolved by business context
    ↓
Resolve customer           "Sharma Builders" → one synthetic customer record
    ↓
Resolve product            "Ultratech cement" → one catalogue SKU, unit bag
    ↓
Resolve date               "parso" → 2026-10-15 (relative to when the user spoke)
    ↓
Resolve historical quote   quote given 2026-10-15: ₹420/bag, valid until 2026-11-15
                           spoken ₹420 matches the quote, so no confirmation is needed
    ↓
Inventory / tax            stock available; synthetic rule GST-2026-KA-CEM (CGST 14% + SGST 14%)
                           ₹84,000.00 + ₹23,520.00 tax = ₹1,07,520.00
    ↓
Policy + risk              APPROVAL_REQUIRED: consequential financial action
    ↓
Exact plan                 create_order → create_invoice_draft → dispatch_order
                           "Nothing has been executed."
                           SEND_NOTIFICATION: not supported, will not be performed
    ↓
Approval                   an authenticated OWNER approves this plan's approval id
    ↓
Execution                  three writes, each under its own idempotency key
    ↓
Read-back verification     order DRAFT ✓   invoice DRAFT ✓   dispatch DISPATCHED ✓
    ↓
Audit                      run ends HANDOFF: the unsupported WhatsApp notification is
                           handed to an operator, not claimed as sent
```

The tax rate comes from a versioned rule in the synthetic dataset. The architecture does
not assume one rate for every cement transaction.

### 3. When reality doesn't line up, nothing executes silently

Each row is covered by an evaluation-sandbox scenario (A–J,
[`evaluation/scenarios.py`](apps/api/src/vaaniflow/evaluation/scenarios.py)) or an
integration test; both run through the production orchestrator and judge the outcome
from the resulting repository state:

| Situation | Outcome |
|---|---|
| Two customers match "Sharma Builders" | `CLARIFY`: no write |
| "UltraTech cement" matches several SKUs | `CLARIFY`: no write |
| ASR hears "2000 bags" | `CONFIRM`: the quantity is kept and flagged as unusually large; approval is still required afterwards |
| The referenced quote has expired | `HUMAN_HANDOFF`: the stale price is not applied |
| No quote exists on the referenced date | `CLARIFY`: no other quote is substituted |
| Only part of the quantity is in stock | `HUMAN_HANDOFF`: no dispatch |
| "Dispatch **mat** karo" (negated) | `CLARIFY`: the negated action is never planned |
| An identical order is already open | `BLOCKED`: no duplicate order |
| Stock changes between approval request and approval | The approval expires; run `FAILED`, nothing written |
| An approval superseded by a newer instruction is used | Refused (`APPROVAL_SUPERSEDED`) |
| Invoice API fails | `PARTIALLY_COMPLETED`: no invoice is claimed and dispatch does not run |
| Dispatch API fails after the invoice | `PARTIALLY_COMPLETED`: the dispatch is not claimed |
| A write times out (may or may not have committed) | `UNKNOWN`: reconciled by read-back, never blindly retried; handed to an operator |

### Run it yourself

```bash
# Start the API with the synthetic business clock, a demo REQUESTER and a demo OWNER
export VAANIFLOW_BUSINESS_CLOCK=synthetic
export VAANIFLOW_API_TOKENS='{
  "demo-requester-token-01": {"actor_id": "22222222-2222-4222-8222-222222222222", "name": "Suresh", "roles": ["REQUESTER"]},
  "demo-owner-token-0001": {"actor_id": "11111111-1111-4111-8111-111111111111", "name": "Ramesh", "roles": ["OWNER"]}
}'
uvicorn vaaniflow.api.app:app

# In a second terminal: every sandbox scenario, scored from actual state
curl -s -X POST localhost:8000/sandbox/evaluate-all
curl -s -X POST localhost:8000/sandbox/scenarios/scenario_c/run   # ambiguous customer

# The canonical note, end to end: Suresh submits it, Ramesh approves it
REQ='Authorization: Bearer demo-requester-token-01'
OWN='Authorization: Bearer demo-owner-token-0001'
RUN=$(curl -s -X POST localhost:8000/runs -H "$REQ" | jq -r .run_id)
curl -s -X POST localhost:8000/runs/$RUN/process -H "$REQ" -H 'Content-Type: application/json' \
  -d '{"text": "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. Invoice bana ke mujhe WhatsApp pe approve karne bhej do."}'
# → status APPROVAL_REQUIRED, with an approval_id. Without a token /approve answers 401;
#   with the REQUESTER token it answers 403 (only an OWNER approves).
curl -s -X POST localhost:8000/runs/$RUN/approve -H "$OWN" -H 'Content-Type: application/json' \
  -d '{"approval_id": "<approval_id>"}'
curl -s localhost:8000/runs/$RUN/audit -H "$OWN"
```

The tokens above are local demo values; never reuse them outside a sandbox. Interactive
API docs are served at `http://localhost:8000/docs`; Swagger's UI does not send the bearer
token, so use curl (or another HTTP client) for the protected routes. Without `VAANIFLOW_BUSINESS_CLOCK=synthetic`
the API uses the real clock, and the synthetic quotes may not match "parso".

---

## Why VaaniOS

| Naive voice agent | VaaniOS |
|---|---|
| Speech → tool call | Speech → typed `SemanticState` → validated plan |
| The model fills in business facts | Business context resolves IDs, prices, stock, tax and dates |
| Ambiguity is resolved by a guess | Ambiguity stays explicit and leads to a clarification |
| "Same rate as before" means whatever was said | The spoken price is checked against the one applicable quote |
| Approval is a conversational "ok" | Approval is bound to the run, plan fingerprint and business snapshot |
| A timeout triggers a retry | `UNKNOWN` is reconciled by read-back before anything is retried |
| A tool response counts as success | Success means the record was read back and verified |
| One failed step hides behind a summary | Per-step outcomes; a partial run is reported as partial |

UNDERSTAND may interpret language, but it must **not invent business facts** (customer
IDs, SKUs, quotes, stock, tax amounts, calendar dates). It also must **not silently
resolve ambiguity** into something that looks executable. ACT decides what happens
using business records and deterministic rules.

---

## Safety by design

These guarantees are implemented and covered by regression tests that check repository
state. [ACT safety semantics](#act-safety-semantics) gives the exact rules.

- **Negation is never inverted.** A negated action is recorded in `negated_actions` and
  never planned.
- **Ambiguity is not a decision.** Alternative customers, products, quantities or
  prices lead to clarification, never to a pick.
- **Approval is bound.** It covers one run, one plan fingerprint and one business
  snapshot. Only an authenticated `OWNER` can give it, and nothing in the request body
  can name the approver.
- **Stale approval is refused.** A changed plan or business snapshot expires the
  approval, and a newer instruction supersedes it.
- **Pricing has one authority.** The execution price comes from exactly one quote valid
  on the business date; a spoken price is only a claim compared against it. No
  applicable quote means no executable sale.
- **UNKNOWN is not FAILED, and not SUCCESS.** A write that may have committed is
  reconciled by read-back by idempotency key and never blindly retried.
- **Every planned write has a verification contract.** A tool without one is never
  planned, and only verified steps are reported as done.
- **Partial execution is reported honestly.** Each step is VERIFIED, FAILED, UNKNOWN or
  NOT_ATTEMPTED. Nothing is rolled back, and no rollback is claimed.
- **No false success.** Messages describe record status as it is (a DRAFT order reads as
  DRAFT), and unsupported actions are named as not performed.

---

## Architecture

VaaniOS has two layers joined by one typed handoff object:

```text
UNDERSTAND   Audio → Preprocessing → ASR → SemanticState → Input evaluation
                                                   ↓
                                       UnderstandResult (handoff)
                                                   ↓
ACT          Context → Validation / risk / policy → Plan → Approval → Execution → Verification → Audit
```

UNDERSTAND answers *what did the human mean, and is it specified well enough to act
on?* ACT answers *given that meaning and what the business knows, what should happen?*
UNDERSTAND never queries business data. ACT never re-interprets language.

```mermaid
flowchart TD
    IN["Voice note / call / API<br/>(audio artifact)"] --> ING["Audio ingestion<br/>write-once artifact storage"]
    ING --> PRE["Audio preprocessing<br/>mono · 16 kHz · PCM16 · measured quality"]
    PRE --> ASR["Speech-to-text<br/>ASRProvider port → Gnani adapter / Mock"]
    ASR --> TR["Transcript"]
    TR --> SC["Semantic compiler<br/>(deterministic, rule-based)"]
    SC --> SS["SemanticState 2.0"]
    SS --> EV["Input evaluation<br/>COMPLETE · PARTIAL · CLARIFICATION_REQUIRED · BLOCKED"]
    EV --> UR["UnderstandResult"]

    UR ==>|"handoff boundary"| CTX

    subgraph ACT ["ACT — implemented (synthetic in-memory business data)"]
        CTX["Business context resolution<br/>customers · products · quotes · stock · tax · dates"] --> VAL["Validation · risk · policy<br/>(deterministic)"]
        VAL --> PLAN["Plan<br/>requested − negated actions · duplicate check"]
        PLAN --> APR["Confirmation / approval / human handoff"]
        APR --> EXE["Execution<br/>idempotency keys · UNKNOWN handling"]
        EXE --> VER["Read-back verification"]
        VER --> AUD["Trace · audit trail"]
    end
```

### Layers inside UNDERSTAND

| Stage | Responsibility | Main code |
|---|---|---|
| Ingestion & storage | Persist the original audio unchanged; artifacts are **write-once** | `infrastructure/storage/local.py`, `application/services/ingest_audio.py` |
| Preprocessing | Decode, down-mix, resample to 16 kHz PCM16 WAV, measure quality, record lineage | `audio/local.py`, `audio/quality.py`, `application/services/preprocess_audio.py` |
| ASR | Provider-neutral port; Gnani and mock adapters | `application/ports/asr.py`, `providers/gnani.py`, `providers/mock.py` |
| Semantic compiler | Transcript → typed `SemanticState`; language only, no business lookups | `semantic/` |
| Input evaluation | Is the semantic request complete, coherent and actionable? | `semantic/evaluation.py` |
| Handoff | One typed object for ACT | `domain/schemas/understand.py`, `application/services/understand.py` |

(Paths are relative to `apps/api/src/vaaniflow/`.)

Dependency direction follows the design: the domain schemas import no framework or
provider code, application services depend on ports, and the Gnani SDK is only
imported inside `providers/gnani.py`.

---

## What the prototype demonstrates

The prototype runs the complete voice-to-business-action loop on synthetic, in-memory
business data: a voice instruction in, and a verified order, invoice draft and dispatch
out (or a clarification, confirmation or handoff when the facts do not support
execution). The HTTP API takes the instruction as text. Audio goes through the Python
services (`UnderstandAudioService`, or the orchestrator's `process_audio_artifact`). The
end-to-end safety architecture is implemented. Production connectors are the next
integration layer:

| Future integration work | Today |
|---|---|
| Production identity provider | Static bearer tokens from an environment variable |
| Persistent storage | In-memory repositories (`SyntheticRepositories`) |
| Production business systems (ERP, inventory, invoicing) | Synthetic dataset (`infrastructure/repositories/synthetic_data.py`) |
| WhatsApp / telephony intake and notifications | Text through the HTTP API, audio through the Python services; notifications are reported as not performed |
| Operator dashboard | HTTP API plus audit and trace endpoints |
| Spoken responses (TTS) | Text messages only |

Some limitations are part of the current design, not only missing connectors: one line
item per request, no catalogue pricing, open search and sandbox routes, and a wide-open
CORS policy. See [Known limitations](#known-limitations) and
[Route authentication boundary](#route-authentication-boundary).

---

> **Technical reference.** The sections below are the engineering detail behind the
> demo: contracts, safety rules, setup, integration and tests.

---

## What UNDERSTAND produces

The ACT side consumes exactly one object: **`UnderstandResult`**
([`domain/schemas/understand.py`](apps/api/src/vaaniflow/domain/schemas/understand.py)).

| Field | Contents |
|---|---|
| `transcript` | What was said: provider-neutral text, language, opaque provider metadata |
| `audio` | Original and processed artifact ids, measured processed-audio metadata, applied operations |
| `semantic_state` | What was understood (`SemanticState`, schema `2.0`) |
| `evaluation` | `actionability` plus structured, machine-readable reasons |

`SemanticState` ([`domain/schemas/semantic.py`](apps/api/src/vaaniflow/domain/schemas/semantic.py))
contains typed slots, each carrying a character span into the transcript and a
rule-tier confidence:

| Slot | Meaning |
|---|---|
| `intent`, `requested_actions[]` | Primary intent and every requested action (with recipient/channel where spoken) |
| `negated_actions[]` | Actions the user explicitly said **not** to perform |
| `customer`, `addressee` | Names **as spoken** — never a customer ID |
| `items[]` | Product mention bound to its own quantity and canonical unit |
| `pricing[]` | Spoken amount and/or historical-price reference, currency, per-unit, item binding |
| `tax` | The spoken instruction only (e.g. "plus GST" → exclusive) — no rate, no amount |
| `references[]` | "same rate", "previous quote", "that order", "it" — with the slot they fill |
| `temporal_expressions[]` | Linguistic offsets/weekdays/dates — never a resolved calendar date |
| `corrections[]` | Superseded and corrected values ("200 — actually 220") |
| `ambiguities[]` | Semantic ambiguity only (entity, value, temporal, action, reference, scope) |
| `compiler`, `source_transcript_id`, `run_id` | Provenance |

Input evaluation ([`semantic/evaluation.py`](apps/api/src/vaaniflow/semantic/evaluation.py))
classifies the state:

| Actionability | Meaning |
|---|---|
| `COMPLETE` | Every required slot is stated and coherent |
| `PARTIAL` | Understood, but a reference ("same rate", "that order") must be resolved by business context |
| `CLARIFICATION_REQUIRED` | The user must supply or disambiguate something |
| `BLOCKED` | Not an actionable request (no intent, empty transcript, unusable audio) |

Each reason has a code, an effect, the slot it concerns, evidence and related ids; the
overall actionability is the most restrictive reason. This is **semantic** completeness
only — it never consults business data and does not replace ACT-side validation or
policy.

---

## Example: the canonical voice note

The scenario from the [Demo](#-demo) is a golden test
([`tests/unit/semantic/test_compiler.py`](apps/api/tests/unit/semantic/test_compiler.py)).
Its compiled state, abridged:

```text
intent             CREATE_DISPATCH_ORDER
addressee          "Suresh"
customer           "Sharma Builders"            (a name, not a customer ID)
items              200 bag × "Ultratech cement"  (not a SKU)
pricing            SPOKEN_WITH_HISTORICAL_REFERENCE
                   420 INR per bag  ← linked to reference "Rate wahi"
tax                GST, EXCLUSIVE ("plus GST")
references         HISTORICAL_PRICE → slot PRICE, anchored to "parso"
temporal           "parso" → DAY_OFFSET:-2, PAST (evidence: qualifies the historical reference)
requested actions  DISPATCH, CREATE_INVOICE_DRAFT,
                   SEND_NOTIFICATION (to speaker, WhatsApp), REQUEST_APPROVAL (by speaker)
urgency            HIGH ("turant")

evaluation         PARTIAL
  - CONTEXT_REFERENCE_UNRESOLVED   "Rate wahi" must be resolved against business records
  - RELATIVE_DATE_NEEDS_CLOCK      "parso" becomes a date only with the run clock + timezone
```

What UNDERSTAND **deliberately does not decide**:

- which customer record "Sharma Builders" is;
- which catalogue SKU "Ultratech cement" is;
- whether ₹420 is actually the quote given two days ago, or still valid;
- whether 200 bags are in stock, the GST amount, or the calendar date of "parso";
- whether anything should be invoiced or dispatched.

Those are ACT responsibilities (see the [Demo](#-demo)). UNDERSTAND itself never
creates an order, invoice or dispatch; ACT does so only after validation and approval.

---

## Safety behaviour of the semantic layer

The compiler must not turn uncertainty into something that looks executable. These
behaviours are covered by regression tests
([`tests/unit/semantic/test_safety_regressions.py`](apps/api/tests/unit/semantic/test_safety_regressions.py)):

| Input | Result |
|---|---|
| "Don't dispatch 200 bags of UltraTech cement to Sharma Builders" | No requested action; `DISPATCH` recorded in `negated_actions`; `CLARIFICATION_REQUIRED` (`NEGATED_ACTION`) |
| "… dispatch mat karo" / "… dispatch nahi karna" | Same — the Hinglish negation is bound to the verb, not the whole sentence |
| "200 bags UltraTech ya ACC cement" / "UltraTech or ACC cement" | Product left empty; `ENTITY_AMBIGUITY` with candidates `UltraTech cement`, `ACC cement` |
| "Dispatch 200 ya 300 bags" / "200 or 300 bags" | Quantity left empty; `VALUE_AMBIGUITY` with candidates `200 bag`, `300 bag` |
| "Sharma Builders ko 2000 bag …" | Stays exactly **2000** — judging whether 2000 is plausible is ACT validation |
| "Send 200 bags, actually 220 …" | Current quantity 220; the correction event keeps 200 as superseded |
| "Dispatch day after tomorrow, not tomorrow …" / "200 bag, nahi nahi, 220 bag" | Treated as corrections — **not** as negation of the action |
| "Sharma Builders ko …, Kumar Constructions ko …" | `ENTITY_AMBIGUITY` on customer instead of picking one |
| "kal" / "parso" / "narso" without tense evidence | `TEMPORAL_AMBIGUITY` instead of guessing past or future |

> [!NOTE]
> These guarantees are about **interpretation**. Unsafe **execution** is prevented by
> ACT (validation, risk/policy, approval and verification); see
> [ACT safety semantics](#act-safety-semantics).

---

## Getting started

### Prerequisites

- **Python 3.12** (the project requires `>=3.12,<3.13`)
- `git`
- A Gnani API key only if you want to call the live speech-to-text service (not needed
  for tests or for the mock pipeline)

Audio decoding uses `soundfile`, whose wheels bundle `libsndfile` on common platforms.

### Install

```bash
git clone https://github.com/VaaniOS/VaaniOS.git
cd VaaniOS

python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

This installs the `vaaniflow` package (from `apps/api/src`) in editable mode together
with the development tools (`pytest`, `pytest-asyncio`, `ruff`, `mypy`).

### Verify the installation

```bash
pytest -q
```

### Environment variables

| Variable | Purpose | Default | Example |
|---|---|---|---|
| `GNANI_API_KEY` | API key read by `gnani.stt.GnaniSTTClient` when no key is passed to its constructor | none (only live Gnani calls need it) | `GNANI_API_KEY=<your-gnani-api-key>` |
| `VAANIFLOW_API_TOKENS` | Bearer tokens → principals for the API (see [Route authentication boundary](#route-authentication-boundary)). JSON map; tokens ≥ 16 characters; roles `OWNER`, `REQUESTER`, `OPERATOR`, `AUDITOR`. A malformed value fails when the app container is first created (the first request), not at import | **unset → every protected route answers 401** | `{"<token>": {"actor_id": "<uuid>", "name": "Ramesh", "roles": ["OWNER"]}}` |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for the demo adapter; environment only, never logged | none (the bot does not start) | `<your bot token>` |
| `TELEGRAM_PRINCIPALS` | Telegram allowlist: numeric user id → principal, same shape as `VAANIFLOW_API_TOKENS` (see [Telegram adapter (demo)](#telegram-adapter-demo)) | **unset → every Telegram user is refused** | `{"<telegram user id>": {"actor_id": "<uuid>", "name": "Demo Owner", "roles": ["OWNER"]}}` |
| `VAANIFLOW_FFMPEG` | FFmpeg executable for Telegram voice notes | `ffmpeg` on PATH | `/usr/bin/ffmpeg` |
| `VAANIFLOW_ASR_LANGUAGE` | Language code passed to the ASR adapter for voice notes (unverified for Hinglish, ADR-017) | adapter default (`en-IN`) | `hi-IN` |
| `VAANIFLOW_ARTIFACT_DIR` | Where voice-note audio artifacts are stored (write-once, kept until deleted; `artifacts/` is git-ignored) | `artifacts` | `/tmp/vaaniflow-artifacts` |
| `VAANIFLOW_BUSINESS_CLOCK` | Business clock: unset = real time; `synthetic` = the synthetic dataset's 2026-10-17 12:00 IST; or a timezone-aware ISO-8601 instant. Invalid values fail, never fall back | real clock | `synthetic` |

```bash
export GNANI_API_KEY="<your-gnani-api-key>"
```

There is no `.env` loader. Never commit keys or tokens (`.env` files are git-ignored).

### Entry points

- **HTTP API**: `uvicorn vaaniflow.api.app:app` serves the FastAPI app
  (`apps/api/src/vaaniflow/api/app.py`; OpenAPI docs at `/docs`). See
  [Run it yourself](#run-it-yourself) and
  [Route authentication boundary](#route-authentication-boundary).
- **Python**: the UNDERSTAND application services, as shown below, and the ACT
  orchestrator (`application/services/orchestrator.py`).

There is no CLI.

---

## Using the pipeline

### Transcript → UnderstandResult

```python
from datetime import UTC, datetime
from uuid import uuid4

from vaaniflow.application.services.understand import UnderstandTranscriptService
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.semantic import InputEvaluator, SemanticCompiler

text = (
    "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
    "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
)
transcript = Transcript(
    transcript_id=uuid4(), provider="mock", text=text, created_at=datetime.now(UTC)
)

service = UnderstandTranscriptService(compiler=SemanticCompiler(), evaluator=InputEvaluator())
result = service.execute(transcript=transcript)

print(result.actionability)  # PARTIAL
print([a.action_type.value for a in result.semantic_state.requested_actions])
print(result.model_dump_json(indent=2))  # the full handoff object
```

### Audio file → UnderstandResult (mock ASR, no network)

```python
import io
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from vaaniflow.application.services.ingest_audio import IngestAudioService
from vaaniflow.application.services.preprocess_audio import PreprocessAudioService
from vaaniflow.application.services.transcribe_audio import TranscribeAudioService
from vaaniflow.application.services.understand import (
    UnderstandAudioService,
    UnderstandTranscriptService,
)
from vaaniflow.audio import LocalAudioPreprocessor, describe_wav
from vaaniflow.domain.schemas.artifact import AudioArtifact
from vaaniflow.infrastructure.storage.local import LocalArtifactStorage
from vaaniflow.providers.mock import MockASR
from vaaniflow.semantic import InputEvaluator, SemanticCompiler

storage = LocalArtifactStorage(Path("./artifacts"))
wav = Path("voice_note.wav").read_bytes()  # a PCM WAV file

artifact_id = uuid4()
artifact = IngestAudioService(artifact_storage=storage).execute(
    artifact=AudioArtifact(
        artifact_id=artifact_id,
        storage_ref=f"local://original/{artifact_id}.wav",
        metadata=describe_wav(artifact_id=artifact_id, wav_bytes=wav),
        created_at=datetime.now(UTC),
    ),
    audio=io.BytesIO(wav),
)

asr = MockASR(text="Sharma Builders ko 200 bags UltraTech cement dispatch karo.")

pipeline = UnderstandAudioService(
    preprocess_audio=PreprocessAudioService(
        artifact_storage=storage, audio_preprocessor=LocalAudioPreprocessor()
    ),
    transcribe_audio=TranscribeAudioService(artifact_storage=storage, asr_provider=asr),
    understand_transcript=UnderstandTranscriptService(
        compiler=SemanticCompiler(), evaluator=InputEvaluator()
    ),
)
result = pipeline.execute(artifact=artifact, run_id=uuid4(), language_hint="hi-IN")

print(result.audio.processed_metadata.quality_class, result.actionability)
```

The original audio is stored under `artifacts/original/` and the processed 16 kHz WAV
under `artifacts/processed/<artifact-id>.wav`. Storage is write-once: storing to an
existing reference raises `ArtifactAlreadyExistsError`. Stage failures raise typed port
errors (`ArtifactStorageError`, `AudioPreprocessorError`, `ASRProviderError`); no
transcript or semantic state is fabricated.

To use Gnani instead of the mock, replace `asr` as shown in the next section.

---

## Gnani speech-to-text integration

The adapter lives in [`providers/gnani.py`](apps/api/src/vaaniflow/providers/gnani.py)
and implements the provider-neutral `ASRProvider` port
([`application/ports/asr.py`](apps/api/src/vaaniflow/application/ports/asr.py)). It wraps
the `gnani-vachana` SDK (`gnani.stt.GnaniSTTClient`), which is a declared dependency.

```python
from gnani.stt import GnaniSTTClient

from vaaniflow.providers.gnani import GnaniASRProvider

client = GnaniSTTClient()  # reads GNANI_API_KEY from the environment
asr = GnaniASRProvider(client=client)  # format="verbatim", itn_native_numerals=False by default
```

What the adapter does:

- calls `GnaniSTTClient.transcribe_bytes` with a filename hint derived from the
  artifact's MIME type (`audio.wav`, `audio.ogg`, `audio.mp3`, …);
- uses `ASRInput.language_hint` as the language code, defaulting to `en-IN`;
- exposes the SDK's `format` (`"verbatim"` or `"transcribe"`, the latter enabling
  inverse text normalisation) and `itn_native_numerals` options;
- maps the response into the provider-neutral `Transcript`; `model`,
  `processing_time` and `end_to_end_latency` are kept as opaque `provider_metadata`;
- leaves `detected_languages` empty, because the REST response reports no language
  detection;
- maps failures to typed errors:

| Situation | Error |
|---|---|
| SDK `InvalidAudioError` | `ASRProviderInvalidInputError` |
| SDK `AuthenticationError`, `APIError`, network `OSError` | `ASRProviderUnavailableError` |
| SDK `ValueError` (bad language code / format) | `ASRProviderConfigurationError` |
| `success: false`, missing/empty transcript, non-dict payload, anything else | `ASRProviderError` |

Isolation: nothing outside `providers/gnani.py` imports the Gnani SDK. Tests use a fake
client ([`tests/unit/providers/test_gnani.py`](apps/api/tests/unit/providers/test_gnani.py),
[`tests/integration/test_understand_pipeline.py`](apps/api/tests/integration/test_understand_pipeline.py)),
so the suite needs no credentials or network.

> [!WARNING]
> The live Gnani API has **not** been exercised by this repository's tests. The
> assumption that this SDK fulfils the "Prisma" ASR role in the design documents, and
> the default language/ITN settings for Hinglish speech, are recorded as unverified in
> [ADR-017](System-Design/18-architecture-decisions.md). Do not treat the live
> integration as production-ready.

---

## Testing

```bash
pytest -q
```

At the time of writing the suite collects and passes **696 tests**. No test needs
credentials or network access.

What they prove, with exact-value assertions and checks on repository state rather than
on messages:

- **Semantic safety**: negation, ambiguity (customer, product, quantity, price),
  numeric fidelity ("2000" stays 2000), corrections, temporal references
- **Approval**: binding to run, plan and snapshot; stale and superseded approvals;
  authenticated OWNER approvers only
- **Authentication**: configured tokens only; no header, token-format or body
  impersonation; run ownership; escalated and closed runs cannot be reopened
- **Pricing**: quote validity, the temporal quote match for "parso", spoken price as a
  claim, no fallback quote
- **Execution**: idempotency, `UNKNOWN` outcomes and reconciliation, partial execution,
  read-back verification, duplicate order detection
- **Workflow**: confirmation, clarification, operator resolution, escalation, the audit
  trail, ACT orchestration and the HTTP API
- **Sandbox**: scenarios A–J through the production orchestrator

| Category | Location | What it covers |
|---|---|---|
| Unit | `apps/api/tests/unit/` | Storage, preprocessing and quality analysis, ASR adapters, tokenizer and number words, compiler, references, corrections, temporal parsing, ambiguity, input evaluation |
| Contract | `apps/api/tests/contracts/` | `SemanticState` and `UnderstandResult` invariants, JSON round-trips, absence of business identifiers, existing ACT-side domain contracts |
| Integration | `apps/api/tests/integration/` | End-to-end UNDERSTAND pipeline with real local storage and WAV preprocessing, mock ASR and a fake Gnani client; ACT orchestration and HTTP API |
| Authentication | `apps/api/tests/integration/test_auth_foundation.py`, `test_p3_authentication.py` | Token map, 401/403 on every run route, header/token-format/body impersonation, OWNER-only approval, recorded actors, run ownership, escalated/closed runs |
| ACT safety regressions | `apps/api/tests/integration/test_act_safety.py`, `test_api_approval.py`, `test_p1_*.py`, `test_p2_hardening.py` | Actionability and negation gates, approval binding and supersession, temporal quote matching, quote validity, pricing authority, UNKNOWN outcomes and reconciliation, partial execution, verification, duplicate orders, confirmation, operator resolution, audit trail — asserting repository state |
| ACT unit | `apps/api/tests/unit/{context,validation,policy,execution,handoff,evaluation,traces,infrastructure}/` | Resolvers, validation engine, policy matrix, tools, verifier, approvals, handoff, sandbox scenarios A–J |
| Telegram | `apps/api/tests/integration/test_telegram_bot.py`, `test_telegram_auth.py`, `test_telegram_phase3.py` | Allowlist identity, ownership, callback integrity, secret redaction; cards and receipts derived from state; partial/UNKNOWN/handoff receipts; voice through the ASR boundary; FFmpeg errors; clarification merging; shared API/Telegram state; HTML injection; dynamic benchmark/status |
| Safety regressions | `apps/api/tests/unit/semantic/test_safety_regressions.py` | Negation, product/customer/quantity/price alternatives, numeric fidelity, fallback products |

Useful subsets:

```bash
pytest -q apps/api/tests/unit
pytest -q apps/api/tests/contracts
pytest -q apps/api/tests/integration
pytest -q apps/api/tests/unit/semantic
pytest -q apps/api/tests/unit/semantic/test_safety_regressions.py
pytest -q -k canonical            # the canonical voice-note tests
```

Semantic tests assert exact extracted values (via a `summarize()` helper in
`tests/unit/semantic/conftest.py`) rather than mere presence.

---

## Quality checks

These are the gates used for every change:

```bash
pytest -q              # full test suite
ruff check .           # lint (configured in pyproject.toml)
ruff format --check .  # formatting check, line length 100
mypy apps/api/src      # static type checking of the source tree
git diff --check       # whitespace errors / conflict markers in the working tree
```

---

## Repository structure

```text
VaaniOS/
├── CLAUDE.md                     # repository operating contract / dev instructions
├── pyproject.toml                # package, dependencies, pytest/ruff/mypy config
├── System-Design/                # canonical architecture and design (01–24, ADRs)
├── docs/
│   ├── HANDOVER.md               # engineering handover and status
│   └── architecture/
│       └── understand-handoff.md # UNDERSTAND → ACT consumer guide
└── apps/
    └── api/
        ├── src/vaaniflow/
        │   ├── domain/
        │   │   ├── schemas/       # SemanticState, UnderstandResult, Transcript, audio
        │   │   ├── models/        # business models used by ACT (orders, quotes, approvals, …)
        │   │   └── policies/      # decision / risk / authorization models
        │   ├── application/
        │   │   ├── ports/         # ArtifactStorage, ASRProvider, AudioPreprocessor, business data
        │   │   ├── schemas/       # ASRInput, preprocessing input/result
        │   │   └── services/      # ingest, preprocess, transcribe, understand,
        │   │                      # orchestrator (ACT), run audit
        │   ├── audio/             # local preprocessor, quality analysis
        │   ├── providers/         # Gnani and mock ASR adapters
        │   ├── infrastructure/
        │   │   ├── storage/       # local write-once artifact storage
        │   │   └── repositories/  # in-memory repositories + synthetic business data
        │   ├── semantic/          # compiler, references, corrections, temporal,
        │   │                      # ambiguity, input evaluation, lexicon
        │   ├── context/           # business-context resolution (ACT)
        │   ├── validation/ policy/ # deterministic validation, risk, policy, confirmation
        │   ├── execution/         # plans, tools, idempotent execution, verifier,
        │   │                      # approvals, duplicate detection
        │   ├── handoff/ traces/   # structured human handoff, run traces
        │   ├── evaluation/        # failure-injection sandbox (scenarios A–J)
        │   ├── api/               # FastAPI app and routers
        │   └── config/
        └── tests/
            ├── unit/
            ├── contracts/
            └── integration/
```

---

## Developer workflow

| You are changing… | Look in |
|---|---|
| A domain contract (`SemanticState`, `UnderstandResult`, transcript, audio metadata) | `apps/api/src/vaaniflow/domain/schemas/` |
| A port or an application service | `apps/api/src/vaaniflow/application/` |
| A provider adapter (ASR) | `apps/api/src/vaaniflow/providers/` |
| Audio preprocessing / quality | `apps/api/src/vaaniflow/audio/` |
| Language understanding or input evaluation | `apps/api/src/vaaniflow/semantic/` |
| Tests | `apps/api/tests/{unit,contracts,integration}/`, mirroring the source layout |
| Architecture decisions | [`System-Design/18-architecture-decisions.md`](System-Design/18-architecture-decisions.md) |

- Work on a feature branch and merge into `main`; the design suggests branches such as
  `feature/audio-semantic` and `feature/agent-execution`
  ([System-Design 16](System-Design/16-development-plan.md)).
- [`CLAUDE.md`](CLAUDE.md) contains the repository's development rules (inspect before
  editing, typed interfaces, no fabricated provider APIs, never bypass validation, keep
  mocks deterministic). It applies to human and AI contributors alike.
- If a change conflicts with `System-Design/`, record the decision as an ADR instead of
  drifting silently.

---

## Current status

### Implemented (UNDERSTAND)

- Audio artifact ingestion with **write-once** local storage and path-traversal protection
- Audio preprocessing to 16 kHz mono PCM16 WAV with **measured** quality metadata
  (peak level, clipping, speech/silence ratio, estimated SNR, noise level, quality class)
- Processed-artifact lineage (source artifact id, applied operations)
- Provider-neutral ASR port with Gnani and mock adapters and typed provider errors
- Transcript contract with opaque provider metadata
- Deterministic semantic compiler for English and romanised Hindi (Hinglish):
  - intent and multiple requested actions (dispatch, invoice draft, approval,
    notification, order create/update/cancel, inventory/price checks), urgency
  - customer, addressee and product mentions; product↔quantity binding into items
  - digits and spoken number words ("chaar sau bees", "do sau", "two hundred")
  - structured pricing and spoken tax instructions
  - references with target slots; corrections with history
  - temporal expressions (relative days incl. kal/parso/narso, weeks, weekdays, dates)
  - semantic ambiguity and action negation
  - character spans, rule-tier confidence and compiler provenance
- Input evaluation with structured reasons
- Typed `UnderstandResult` handoff and end-to-end application services
- Unit, contract, integration and safety-regression tests; architecture docs and ADRs

### Implemented (ACT)

Over synthetic, in-memory business data (`infrastructure/repositories/synthetic_data.py`):

- Context resolution: customers, products, quotes, inventory, tax rules, relative dates
- Deterministic validation, risk scoring and a policy matrix (no LLM decides execution)
- Explicit plans built only from requested − negated actions; one approval per plan
- Approval bound to run, plan fingerprint and business snapshot, re-validated at execution
- Execution with idempotency keys, read-back verification of every write, UNKNOWN handling
- Structured human handoff, bound confirmation, operator resolution of UNKNOWN outcomes
- Business-level duplicate order detection
- Traces, an end-to-end audit endpoint, and a failure-injection sandbox (scenarios A–J)
- Bearer-token authentication with role-based permissions and run ownership on every run
  route (search and sandbox routes are open — see [Route authentication boundary](#route-authentication-boundary))
- FastAPI HTTP API (`apps/api/src/vaaniflow/api/`)

### ACT safety semantics

| Behaviour | Rule |
|---|---|
| Pricing authority | The execution price is the price of exactly one quote valid on the business date. A spoken price is a claim compared against it (mismatch → confirmation). **No applicable quote → no executable sale** (handoff); a referenced rate with no matching quote → clarification. No other quote is substituted. |
| Historical references | "Rate wahi jo parso bataya tha" matches only quotes given on the date of the temporal expression linked to *the price's own reference*. "parso" is resolved against when the user spoke, not when approval happens. |
| Approval | Every business write needs an approval bound to its run, plan fingerprint and business snapshot. A new instruction (or an operator escalation) supersedes any pending approval (`SUPERSEDED`, kept for audit). Approval re-validates; a changed plan or snapshot expires it. Only an authenticated `OWNER` can approve or reject, and the recorded approver is that authenticated actor — never an identity from the request body. |
| Confirmation | A CONFIRM decision creates a confirmation bound to one run, the exact warnings asked about and the business snapshot. A yes/no reply (`POST /runs/{id}/confirm`) answers only that confirmation; if the facts changed it expires. Confirmation never executes — approval is still required. |
| Duplicate orders | An open equivalent order (same customer, items, price, destination) blocks a new one; a completed one blocks only on the same business day. Orders the system creates stay `DRAFT` unless dispatched, so an identical undispatched request stays blocked until that order is handled. If orders cannot be read, nothing is created (handoff). |
| Verification | Every planned write has a read-back contract (`execution/plan.py: VERIFICATION_CONTRACTS`); a tool without one is never planned. Only a verified step is reported as done. |
| UNKNOWN outcomes | A timeout or exception after a write may have committed: the step is `UNKNOWN`, reconciled by read-back by idempotency key, never blindly retried. An operator can resolve it (`POST /runs/{id}/executions/{execution_id}/resolve`); success requires a verified record committed by that exact operation. History (`prior_*`, `resolution`) is never erased. Resolution requires an `OPERATOR`, never runs the remaining steps and never closes the handoff. The audit's `reconciliation` section reports a FAILED outcome whose record nevertheless exists (`FAILED_BUT_RECORD_EXISTS`). |
| Idempotency | Every planned write has a key `run-<run>:plan-<plan>:<tool>`. Repeating the same call returns the stored outcome. A FAILED call is never re-invoked under its key; an UNKNOWN one only after read-back proves nothing was committed. Repeated `/approve` or `/confirm` requests return 409 and repeat nothing. |
| Partial execution | Each step reports VERIFIED / FAILED / UNKNOWN / NOT_ATTEMPTED; runs end `COMPLETED`, `PARTIALLY_COMPLETED`, `FAILED` or `HANDOFF`. Nothing is rolled back and no rollback is claimed. Messages state record statuses (a DRAFT order reads as DRAFT). |
| Authentication | `Authorization: Bearer <token>`, tokens from `VAANIFLOW_API_TOKENS` (ADR-022). Identity and roles come only from the configured token; `X-Role`, `X-User-Id`, `X-Principal-Id` and role-named or bare-UUID tokens have no effect, and no body field can name an actor (422). Approve/reject, confirm, UNKNOWN resolution and escalation are re-checked by the orchestrator. See [Route authentication boundary](#route-authentication-boundary). |
| CORS | **Not restricted**: any origin (`*`) with credentials allowed (`api/app.py`). Bearer tokens are not sent automatically by browsers, but the policy must be narrowed before any deployment. |
| Persistence | All state is in-memory (`SyntheticRepositories`) and lost on restart. |
| Business clock | Production uses the real clock. `VAANIFLOW_BUSINESS_CLOCK=synthetic` (or an ISO-8601 instant) pins the API to the synthetic dataset's 2026-10-17 12:00 IST for demos; the evaluation runner always uses it. |

### Route authentication boundary

Identity comes only from a configured bearer token (ADR-022). Runs are owned by the
principal that created them.

| Route | Who may call it |
|---|---|
| `POST /runs` | `SUBMIT_INSTRUCTION` (`REQUESTER`, `OWNER`, `OPERATOR`); the caller becomes the run owner |
| `POST /runs/{id}/process`, `/clarify` | `SUBMIT_INSTRUCTION` and the run owner (an `OPERATOR` may re-instruct any run). Refused with 409 on an escalated (`HANDOFF`) or settled (`EXECUTING`, `COMPLETED`, `PARTIALLY_COMPLETED`, `FAILED`, `BLOCKED`) run |
| `POST /runs/{id}/approve`, `/reject` | `OWNER` only (the owner approves runs requested by others) |
| `POST /runs/{id}/confirm` | `REQUESTER` for their own run, or `OWNER` |
| `POST /runs/{id}/executions/{execution_id}/resolve` | `OPERATOR` |
| `POST /runs/{id}/handoff` | `OPERATOR`; supersedes everything pending on the run and assigns the case to that operator |
| `GET /runs/{id}`, `/trace`, `/validation` | The run owner, or `AUDITOR` / `OPERATOR` / `OWNER` |
| `GET /runs/{id}/audit` | `AUDITOR`, `OPERATOR` or `OWNER` |
| `GET /customers/search`, `/products/search`, `/quotes/search`, `/inventory/search` | **Open** (synthetic business data) |
| `GET /sandbox/scenarios`, `POST /sandbox/scenarios/{id}/run`, `POST /sandbox/evaluate-all` | **Open**, demo only: scenarios run with the labelled synthetic evaluation actor (`SYNTHETIC_EVALUATION_OWNER`, `synthetic = true`) on fresh repositories isolated from the API's runs and records |

Missing credentials → 401 `AUTHENTICATION_REQUIRED`; an unknown token → 401
`INVALID_CREDENTIALS`; a missing permission or another principal's run → 403. Approvals,
confirmations and UNKNOWN resolutions record the acting principal (`approved_actor`,
`rejected_actor`, `confirmed_actor`, `resolved_actor`); `actor_authenticated` is true only
for a credential-authenticated approver or rejecter.

**Known limitations:**

- **Static tokens**: no expiry, rotation, rate limiting or user management.
- **Open routes**: the search routes expose (synthetic) business data; the sandbox routes
  must not be exposed outside a demo environment.
- **CORS** allows any origin (see [ACT safety semantics](#act-safety-semantics)).
- **Telegram adapter**: see [Telegram adapter (demo)](#telegram-adapter-demo).

### Telegram adapter (demo)

`presentation/telegram_bot.py` is a demo adapter. It uses the same principals and the
same authorization rules as the HTTP API:

```text
Telegram user id ──► TELEGRAM_PRINCIPALS allowlist ──► Principal (actor id, roles,
"telegram-allowlist") ──► permissions, run ownership, run state ──► orchestrator
```

- **Identity**: only an allowlisted numeric Telegram user id becomes a principal. Unknown
  users are refused (the bot replies with their user id so the operator can add it) and
  nothing is created. Usernames, display names, chat ids and button data never
  contribute identity or roles. An unset `TELEGRAM_PRINCIPALS` refuses everyone; a
  malformed one stops the bot at startup.
- **Chats**: private chats only. Group chats, and updates whose sender is not the chat,
  are refused.
- **Ownership**: a run started from Telegram is owned by the user's principal. Each user's
  messages only ever continue their own open run; a settled or escalated run is never
  reopened (the next message starts a new run). Clarify is refused for another user's run.
- **Approval / rejection**: only an allowlisted `OWNER` (checked by the orchestrator, not
  by hiding buttons). Approvals record `approved_actor` / `rejected_actor` with
  `authentication_method = "telegram-allowlist"`. A stale button (approved, rejected,
  expired, superseded, escalated, from before a restart, or for another run) changes
  nothing.
- **Confirmation**: Yes/No buttons on a confirmation; only the requester of that run (or
  an `OWNER`) may answer.
- **Buttons**: `callback_data` is untrusted input, parsed against a fixed grammar with
  compact ids (within Telegram's 64-byte limit); anything else is refused without
  reaching business logic. A failing update is logged and reported; it never stops
  polling.
- **Secrets**: `TELEGRAM_BOT_TOKEN` is read from the environment only. Telegram API
  errors are re-raised without the request URL, and the token is redacted from the
  adapter's and httpx's log records.

**What Telegram shows** is rendered from backend state only (`presentation/telegram_views.py`),
with every dynamic value HTML-escaped:

- **Approval card**: what was understood (customer, item, quantity, spoken price and its
  source, tax instruction, time references, requested and negated actions, urgency), the
  business records used (customer, product, quote and its validity, price used, stock,
  tax rule and amounts), every validation check with its result, risk, the planned
  operations in their real order, and unsupported actions that will be handed off.
- **Receipt**: one line per planned step with its real status (`VERIFIED`, `FAILED`,
  `UNKNOWN`, `NOT ATTEMPTED`). The header follows the run status: complete only when every
  step is verified; *partially completed*; *outcome unknown* (with "no automatic retry");
  *completed with handoff* when an unsupported action (e.g. WhatsApp) was not performed.
  An expired approval shows an alert and no receipt.
- **`/benchmark`** runs `EvaluationRunner().run_all()` and shows its actual result;
  **`/status`** reads counts from the repositories. **`/demo`** sends the fixed canonical
  instruction through the normal pipeline; its card is computed like any other.

**Voice notes** (`application/services/voice_intake.py`): Telegram audio → FFmpeg
(`infrastructure/audio/ffmpeg.py`: `VAANIFLOW_FFMPEG` or `ffmpeg` on PATH, 30 s timeout,
pipes only) → 16 kHz mono PCM16 WAV → write-once ingest → preprocessing with measured
quality → the Gnani ASR adapter → the same pipeline as text (unusable audio is blocked by
Input Evaluation). Voice is enabled only when `GNANI_API_KEY` is set; otherwise voice notes
are refused. Any conversion, ASR or empty-transcript failure is reported and creates no
run; the caption and the demo text are never used instead. The live Gnani API has not been
exercised by the automated tests (ADR-017).

Voice processing writes local runtime artifacts: the converted original recording and the
preprocessed 16 kHz WAV of every voice note, under `artifacts/` (relative to the working
directory) or `VAANIFLOW_ARTIFACT_DIR`. They are kept until you delete them (prototype: no
retention policy) and `artifacts/` is excluded from Git; never commit or share them.

**Clarification replies** are merged (`application/services/clarification_merge.py`): a
short reply such as "Sharma Builders" or "10 bag" fills only the slot the open
clarification asked for (customer, product or quantity); everything already understood is
kept; the merged request is re-evaluated and goes through context, validation and
approval again. A reply naming actions is a new instruction; a reply that answers nothing
asked, or changes another fact, changes nothing. The HTTP `/clarify` route uses the same
merge.

**One process, one state**: run the API and the bot together so both use the same
application container (runs, approvals and audits are shared):

```bash
export TELEGRAM_BOT_TOKEN='<your bot token>'
export TELEGRAM_PRINCIPALS='{"<your numeric Telegram user id>": {"actor_id": "00000000-0000-4000-8000-00000000d001", "name": "Demo Owner", "roles": ["OWNER", "REQUESTER"]}}'
export VAANIFLOW_API_TOKENS='{"demo-auditor-token-0001": {"actor_id": "00000000-0000-4000-8000-00000000a001", "name": "Auditor", "roles": ["AUDITOR"]}}'
export VAANIFLOW_BUSINESS_CLOCK=synthetic   # the synthetic quotes are dated around 2026-10-17
export GNANI_API_KEY='<optional: enables voice notes>'
python -m vaaniflow.presentation.serve      # HTTP API on :8000 + Telegram bot
```

`python -m vaaniflow.presentation.telegram_bot` runs the bot alone (its own state). Message
the bot once without `TELEGRAM_PRINCIPALS` to learn your user id. State is in memory and
lost on restart; separate processes do not share state. Concurrent HTTP requests and bot
updates share the in-memory repositories without locking (prototype).

### Next (not implemented)

- Production identity: an identity provider with expiring, rotatable credentials
  (today's static bearer tokens are a sandbox mechanism)
- Persistent storage (all repositories are in-memory)
- Operator dashboard, WhatsApp/telephony integrations
- Text-to-speech responses (Gnani Timbre in the design)
- Multi-item orders, catalog or operator-set pricing

---

## Design principles

1. **Speech is not an action.** A transcript is untrusted input that becomes typed state
   before anything else happens.
2. **Semantic interpretation is not business truth.** Names stay names; IDs, prices,
   stock and dates come from business systems.
3. **Ambiguity must remain ambiguity.** Alternatives are surfaced with their candidates,
   never silently resolved.
4. **Corrections are first-class information.** The corrected value is current; the
   superseded value is preserved.
5. **Negation must never silently invert intent.** "Don't dispatch" is recorded as a
   negated action, not a dispatch.
6. **Business facts belong to business context**, not to model output.
7. **Consequential execution requires validation, approval and verification.**
8. **Provider integrations stay replaceable** behind ports.
9. **Domain contracts are explicit and typed** — strict Pydantic models that reject
   unknown fields.
10. **Every discovered failure becomes a regression test.**

---

## Known limitations

- **Audio formats:** only WAV input is tested. The local preprocessor decodes through
  `libsndfile`; in a manual check with the bundled libsndfile 1.2.2 it also decoded
  FLAC, Ogg Vorbis, Ogg Opus and MP3, but these paths are untested. M4A/AAC is not
  supported, and `describe_wav` always labels metadata as `audio/wav`.
- **No advanced audio processing:** no VAD trimming, noise suppression,
  dereverberation or speech enhancement. Quality analysis is a frame-energy heuristic.
- **Devanagari transcripts** are not interpreted (they evaluate to `BLOCKED`, not to
  wrong facts).
- **Irregular Hindi number words** for 21–99 (e.g. "pachchis") are not parsed.
- **Hedged quantities** ("around 200", "lagbhag 200") are treated as exact values.
- **Live Gnani API** is not used by the automated tests; language/ITN defaults are
  unverified.
- **No ASR confidence propagation** — semantic confidence is rule-tier and ordinal,
  not a calibrated probability.
- **Unknown products** without a known category noun are captured positionally at low
  confidence (e.g. "200 bags Birla Gold" → 0.55) and must be resolved downstream.
- **Negation coverage** is bounded to the supported English/Hinglish patterns
  (don't / do not / never; mat / nahi / nahin); "dispatch karo nahi to …" is
  conservatively treated as negation.
- **Unusable audio still reaches ASR**; input evaluation blocks it afterwards.
- **No event/commitment extraction** ([System-Design 21](System-Design/21-event-system.md)).
- **ACT runs on synthetic in-memory data only**; nothing is persisted across restarts.
- **One line item per request**; multi-item requests are clarified, not executed.
- **No catalog prices**: a customer without an applicable quote cannot be sold to by
  voice (ADR-019). `ACCEPTED` quotes are not treated as executable pricing because the
  model does not define their semantics.
- **Clarification merging is slot-limited**: a short reply fills only a missing or
  ambiguous customer, product or quantity of a single-item request; other gaps (price,
  date, multiple items) need the complete corrected instruction.
- **Sandbox authentication**: static bearer tokens from an environment variable, no
  expiry, rotation, rate limiting or user management. The permission and run-ownership
  boundary is enforced; the credential store is not production-grade. Search and sandbox
  routes are open and CORS is unrestricted (see [Route authentication boundary](#route-authentication-boundary)).
- **Not production-ready**: in-memory state, synthetic data, sandbox authentication.
- **Relative dates**: only day offsets (kal/parso/…) are resolved; a spoken weekday or
  explicit date linked to a rate is treated as unresolved (clarification).
- `numpy` is imported directly but is only installed transitively (via `scipy`).

---

## Documentation map

| Document | Contents |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Mission, engineering principles and development rules |
| [System-Design/README.md](System-Design/README.md) | Index of the design documents |
| [01 · System overview](System-Design/01-system-overview.md) | Product boundary, goals, trust boundary, layers |
| [02 · Architecture](System-Design/02-architecture.md) | Components, runtime topology, dependency direction |
| [03 · Data model](System-Design/03-data-model.md) | Domain entities and provenance |
| [04 · Audio pipeline](System-Design/04-audio-pipeline.md) | Preprocessing and quality design |
| [05 · Semantic compiler](System-Design/05-semantic-compiler.md) | Voice-to-structured-state design |
| [06 · Context resolution](System-Design/06-context-resolution.md) | ACT: entity, quote, inventory and temporal resolution |
| [08 · Validation, policy, risk](System-Design/08-validation-policy-risk.md) | ACT: deterministic safeguards |
| [09 · Execution & verification](System-Design/09-execution-verification.md) | ACT: approval, idempotency, read-back |
| [16 · Development plan](System-Design/16-development-plan.md) | UNDERSTAND / ACT team split |
| [18 · Architecture decisions](System-Design/18-architecture-decisions.md) | ADR-001 … ADR-023 (ADR-022: authentication; ADR-023: Telegram presentation) |
| [20 · Gnani integration](System-Design/20-gnani-integration.md) | Provider adapter strategy |
| [docs/architecture/understand-handoff.md](docs/architecture/understand-handoff.md) | UNDERSTAND → ACT handoff contract and consumer rules |

The remaining design documents (agent orchestration, human handoff, sandbox, observability,
API contracts, security, frontend, demo scenarios, testing strategy, events, repository
blueprint, state machines, agent reliability) are listed in
[System-Design/README.md](System-Design/README.md). They describe intended behaviour;
parts of it (dashboard, events, TTS, production integrations) are not implemented yet.

---

## Contributing

1. Make one focused change at a time; do not mix unrelated refactors or formatting.
2. Add or update tests — exact-value assertions for semantic behaviour, and a regression
   test for every bug you fix.
3. Run the [quality checks](#quality-checks) before opening a pull request.
4. Update `System-Design/` (or add an ADR) when a contract or behaviour changes.
5. Never commit secrets or real customer data; demo data must be clearly synthetic.
6. Respect the UNDERSTAND / ACT boundary: the semantic layer interprets language and
   must not query or invent business facts.

---

## License

No license is currently specified for this repository.

Until a license is added, the repository should be treated as all rights reserved.
