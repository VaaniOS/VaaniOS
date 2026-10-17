# CLAUDE.md — VaaniFlow
## Speak it. Structure it. Execute it.

This file is the operating contract for Claude Code working on the VaaniFlow project.

---

# 1. PROJECT MISSION

VaaniFlow is an agentic voice-to-business-action platform for Indian SMEs.

Core idea:

> Raw speech should never directly become an irreversible business action.

The system accepts messy, multilingual, noisy real-world voice instructions and converts them into structured, context-aware, validated business workflows.

Primary demo scenario:

Ramesh runs a wholesale cement/steel business in Peenya Industrial Area. On a noisy shop floor, he sends an ~8-second WhatsApp voice note:

"Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. Invoice bana ke mujhe WhatsApp pe approve karne bhej do."

The platform must:

1. Process noisy audio.
2. Transcribe it using Gnani Prisma (or a mock adapter during development).
3. Convert speech into structured semantic state.
4. Resolve customer/product/time/price references using business data.
5. Validate every consequential fact.
6. Decide whether to execute, clarify, request approval, or hand off to a human.
7. Never claim an action succeeded unless the tool result proves it.
8. Generate a draft invoice and approval request.
9. Execute only after required approval.
10. Verify downstream actions.
11. Provide spoken feedback through Gnani Timbre (or a mock adapter).
12. Record a complete trace for debugging/evaluation.

The project is NOT a generic voice chatbot, invoice generator, WhatsApp bot, or ASR demo.

Its differentiator is the reliability/semantic layer between human speech and autonomous business action.

---

# 2. NON-NEGOTIABLE ENGINEERING PRINCIPLES

## 2.1 Speech is not state

Never pass raw transcript directly into business execution.

Required flow:

Audio
→ Audio Quality / Preprocessing
→ ASR
→ Semantic Voice Preprocessor
→ Structured Intent
→ Context Resolution
→ Validation / Policy
→ Decision
→ Tool Execution
→ Verification
→ Response

## 2.2 LLMs must not invent business facts

Customer IDs, product IDs, prices, stock, tax values, quote dates, invoice numbers, and execution status must come from tools/data.

Bad:

"The price is ₹420 because the model remembers it."

Good:

"Historical quote lookup returned ₹420/unit on 2026-10-15."

## 2.3 Ambiguity is first-class state

Do not silently guess.

Represent ambiguity explicitly.

Examples:

- multiple customers match "Sharma Builders"
- "same rate" could refer to several quotes
- "parso" has a relative date meaning
- "200 bags" vs "2000 bags" has high financial impact
- "UltraTech cement" may map to multiple SKUs

The system must decide whether ambiguity is harmless, clarifiable, or dangerous.

## 2.4 Corrections are semantic operations

Example:

"Send 200—actually 220 bags."

The final structured state must contain 220, and the trace must preserve that 200 was superseded.

Do not simply concatenate both values.

## 2.5 Consequential actions require stronger guarantees

Risk-sensitive operations include:

- order creation
- price selection
- invoice generation
- payment initiation
- dispatch
- external customer notification

Use approval/confirmation when policy requires it.

## 2.6 Never fake success

If an invoice API fails:

DO NOT say:
"Invoice created."

Say:
"The invoice could not be created. I have kept the validated draft."

Execution status must come from tool results.

## 2.7 Verify after executing

A successful tool call is not automatically proof that the business state changed.

Where possible:

execute
→ retrieve/read-back
→ compare expected vs actual
→ mark VERIFIED or UNVERIFIED

## 2.8 Keep provider-specific code behind adapters

Do not scatter Gnani-specific calls throughout the application.

Use interfaces such as:

- ASRProvider
- TTSProvider
- AgentProvider if required
- VoiceAuthProvider if officially supported

The rest of the application must work with mocks.

Never invent undocumented Gnani APIs, model names, versions, latency numbers, authentication mechanisms, or capabilities.

---

# 3. PRODUCT SCOPE

## MVP

The first working version MUST support:

1. Voice file upload.
2. Audio quality analysis.
3. Noise/silence preprocessing.
4. ASR adapter.
5. Semantic Voice Preprocessor.
6. Structured intent schema.
7. Customer lookup.
8. Product lookup.
9. Historical quote lookup.
10. Inventory lookup.
11. Tax/rules calculation through a business rules tool.
12. Validation engine.
13. Decision engine.
14. Human clarification/handoff.
15. Invoice draft.
16. Approval workflow.
17. Simulated dispatch.
18. Verified execution.
19. Spoken response adapter.
20. End-to-end trace.
21. Failure injection sandbox.
22. Evaluation metrics.

Do NOT start with every possible domain.

Build the wholesale construction-material workflow first.

---

# 4. RECOMMENDED ARCHITECTURE

Use a modular monorepo.

Suggested structure:

/
├── CLAUDE.md
├── README.md
├── .env.example
├── docker-compose.yml
├── Makefile
├── apps/
│   ├── api/
│   │   ├── src/
│   │   │   └── vaaniflow/
│   │   │       ├── api/
│   │   │       ├── domain/
│   │   │       ├── application/
│   │   │       ├── infrastructure/
│   │   │       ├── providers/
│   │   │       ├── audio/
│   │   │       ├── semantic/
│   │   │       ├── context/
│   │   │       ├── validation/
│   │   │       ├── policy/
│   │   │       ├── decisions/
│   │   │       ├── execution/
│   │   │       ├── handoff/
│   │   │       ├── traces/
│   │   │       ├── evaluation/
│   │   │       └── config/
│   │   └── tests/
│   ├── web/
│   │   ├── app/
│   │   ├── components/
│   │   ├── lib/
│   │   └── types/
│   └── worker/
├── packages/
│   ├── schemas/
│   ├── mock-business/
│   └── evaluation-cases/
├── data/
│   ├── customers/
│   ├── products/
│   ├── quotes/
│   ├── inventory/
│   └── scenarios/
├── docs/
│   ├── architecture/
│   ├── decisions/
│   └── demo/
└── scripts/

Adapt the exact layout to the repository if an existing structure is already present. Do not unnecessarily rewrite a working project.

---

# 5. BACKEND STACK

Preferred:

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy
- PostgreSQL
- Redis where asynchronous jobs/caching are actually useful
- pytest
- Ruff
- mypy if practical

Use TypeScript/Next.js for the dashboard.

Use Docker Compose for local infrastructure.

Avoid unnecessary microservices.

For the hackathon MVP, a modular monolith plus worker is preferable to a distributed system.

---

# 6. FRONTEND

Build a polished operator dashboard, not a generic admin template.

Main views:

## 6.1 Voice Intake

Show:

- uploaded audio
- audio quality score
- detected language/code-switching
- preprocessing status
- transcript
- transcript confidence where available

## 6.2 Semantic State

Show:

- intent
- customer
- recipient
- products
- quantities
- prices
- dates
- constraints
- corrections
- references
- ambiguities
- confidence
- actionability

Make unresolved fields visually obvious.

## 6.3 Business Context

Show evidence used to resolve:

- customer match
- product match
- historical quote
- inventory
- tax calculation

Every important business fact should have provenance.

## 6.4 Decision Panel

Possible states:

- EXECUTE
- CLARIFY
- CONFIRM
- APPROVAL_REQUIRED
- HUMAN_HANDOFF
- BLOCKED

Explain WHY.

## 6.5 Execution Trace

Timeline:

Audio
→ Preprocessing
→ ASR
→ Semantic Parse
→ Context Lookup
→ Validation
→ Decision
→ Tool Call
→ Tool Result
→ Verification
→ Final Response

## 6.6 Sandbox

Allow evaluator to toggle failures:

- ASR number error
- duplicate customer
- ambiguous product
- stale quote
- inventory shortage
- invoice API failure
- dispatch API failure
- environment change

Then rerun the same request.

This is one of the most important demo surfaces.

---

# 7. AUDIO PREPROCESSING

Audio preprocessing is a real subsystem, not a decorative step.

Pipeline:

Raw Audio
→ format normalization
→ VAD
→ silence trimming
→ noise estimation
→ selective noise suppression
→ dereverberation where appropriate
→ speech enhancement
→ gain/loudness normalization
→ clipping detection
→ audio quality analysis
→ ASR

Potential libraries/tools:

- FFmpeg
- WebRTC Audio Processing
- Silero VAD
- RNNoise
- DeepFilterNet
- librosa
- PyTorch

Do not blindly apply every transformation.

The preprocessing controller should first assess audio.

Example quality metadata:

{
  "duration_ms": 8120,
  "estimated_snr_db": 7.8,
  "speech_ratio": 0.71,
  "clipping_detected": false,
  "noise_level": "high",
  "audio_quality": "degraded"
}

Preserve original audio.

Store the processed artifact separately.

Do not destroy evidence.

---

# 8. GNANI PROVIDER ADAPTERS

Create provider interfaces.

Example conceptual interfaces:

class ASRProvider:
    async def transcribe(self, audio: AudioArtifact) -> Transcript:
        ...

class TTSProvider:
    async def synthesize(self, text: str, language: str) -> AudioArtifact:
        ...

Do NOT tightly couple the domain layer to Gnani.

Implement:

- MockASRProvider
- GnaniPrismaProvider
- MockTTSProvider
- GnaniTimbreProvider

Only implement real Gnani integration once official credentials/API documentation is available.

If official documentation is absent:

- use mocks
- isolate the integration point
- clearly label assumptions
- do not fabricate endpoints

---

# 9. VOICE PREPROCESSOR — CORE COMPONENT

The Voice Preprocessor is NOT merely JSON extraction.

It is a semantic compiler from speech to structured business state.

Input:

- transcript
- language metadata
- ASR confidence
- conversation history if applicable

Output:

- intent
- entities
- references
- constraints
- temporal expressions
- corrections
- ambiguities
- confidence
- actionability
- requested actions

Current contract (supersedes the earlier v1 example that stood here):

- `SemanticState` schema 2.0 — `apps/api/src/vaaniflow/domain/schemas/semantic.py`
  (typed `customer`, `addressee`, product-bound `items`, structured `pricing`,
  `tax`, slot-targeted `references`, `temporal_expressions`, `corrections`,
  semantic `ambiguities`, `requested_actions`, `negated_actions`, spans,
  compiler provenance). See ADR-015 and ADR-018.
- Actionability is not part of SemanticState: it is produced by Input
  Evaluation and handed to ACT inside `UnderstandResult`
  (`apps/api/src/vaaniflow/domain/schemas/understand.py`, ADR-013).
- The canonical Ramesh note compiles to CREATE_DISPATCH_ORDER, customer
  "Sharma Builders", item 200 bag "Ultratech cement", price 420 INR/bag
  linked to the "Rate wahi" reference, GST exclusive, "parso" = DAY_OFFSET:-2
  (past), actions DISPATCH / CREATE_INVOICE_DRAFT / SEND_NOTIFICATION /
  REQUEST_APPROVAL, urgency HIGH, actionability PARTIAL — see the golden test
  `apps/api/tests/unit/semantic/test_compiler.py`.
- Consumer guide: `docs/architecture/understand-handoff.md`.

The schema must be typed and versioned.

---

# 10. ENTITY RESOLUTION

Entity resolution must be deterministic where possible.

Customer:

"Sharma Builders"

may map to:

customer_id = CUST-0042

but if there are multiple candidates:

DO NOT select arbitrarily.

Return:

{
  "status": "AMBIGUOUS",
  "candidates": [...]
}

Product resolution must consider:

- brand
- product family
- SKU
- unit
- packaging
- regional naming
- aliases

Example:

"cement"

is not automatically equivalent to a particular SKU.

---

# 11. TEMPORAL REASONING

Relative terms:

- today
- tomorrow
- yesterday
- parso
- kal
- next Friday
- last Friday

must be normalized using the business timezone and current date.

Never let the LLM silently invent dates.

Store:

- original expression
- normalized date
- timezone
- resolution source
- confidence

Example:

{
  "surface": "parso",
  "resolved_date": "2026-10-15",
  "timezone": "Asia/Kolkata",
  "resolution_method": "relative_date_resolver"
}

---

# 12. HISTORICAL PRICE RESOLUTION

For:

"Rate wahi lagana jo parso bataya tha"

the agent must call a historical quote service.

Required logic:

1. Resolve customer.
2. Resolve product.
3. Resolve date.
4. Search quotes.
5. Check quote status.
6. Check expiry.
7. Check currency/unit.
8. Check whether quote is customer-specific.
9. Return evidence.

Never infer a price from the transcript alone if business records exist.

Example:

{
  "quote_id": "Q-1092",
  "customer_id": "CUST-0042",
  "product_id": "PROD-CEM-001",
  "quoted_unit_price": 420,
  "currency": "INR",
  "quoted_on": "2026-10-15",
  "status": "VALID"
}

---

# 13. TAX AND BUSINESS RULES

Do not hard-code universal tax assumptions into LLM prompts.

Create a rules service/tool.

Example:

calculate_tax(
    customer,
    product,
    quantity,
    unit_price,
    jurisdiction,
    transaction_type
)

Return:

- taxable value
- tax components
- tax rate
- total
- rule/version/provenance

The Ramesh scenario may use a specific tax outcome for the demo dataset, but the architecture must not imply that every cement transaction universally uses the same rate.

---

# 14. VALIDATION ENGINE

Validation should be deterministic where possible.

Checks:

### Identity
- customer resolved?
- recipient resolved?
- product resolved?

### Quantity
- quantity present?
- unit compatible?
- suspicious magnitude?

### Pricing
- price source?
- quote valid?
- quote matches customer/product?
- stale?

### Inventory
- enough stock?
- reserved stock?
- warehouse/location?

### Tax
- rules available?
- calculation successful?

### Financial risk
- transaction value
- threshold
- unusual deviation from historical price

### Execution
- approval required?
- tool available?
- duplicate order risk?

Return structured validation results.

Example:

{
  "status": "BLOCKED",
  "issues": [
    {
      "code": "AMBIGUOUS_CUSTOMER",
      "severity": "HIGH",
      "message": "Two customers match 'Sharma Builders'."
    }
  ]
}

---

# 15. DECISION ENGINE

Never allow the LLM alone to determine whether a consequential action should happen.

Use a policy/decision layer.

Possible decisions:

- EXECUTE
- CLARIFY
- CONFIRM
- APPROVAL_REQUIRED
- HUMAN_HANDOFF
- BLOCKED

Inputs:

- semantic state
- business context
- validation results
- risk
- reversibility
- confidence
- user authorization
- tool availability

Example:

High confidence + validated + low risk
→ execute

High confidence + consequential financial action
→ approval

Low confidence in customer identity
→ clarify

Business data conflict
→ human handoff

Tool failure
→ preserve draft, do not claim success

---

# 16. RISK MODEL

Implement a simple interpretable risk score.

Factors:

- semantic uncertainty
- entity ambiguity
- financial value
- reversibility
- external side effects
- data sensitivity
- policy constraints
- tool reliability

Do NOT hide all decision logic inside an LLM.

The UI should be able to explain:

"Blocked because customer identity is ambiguous and dispatch is irreversible."

---

# 17. HUMAN HANDOFF

Human handoff is not:

"Please contact support."

Generate a structured handoff packet.

Example:

{
  "case_id": "HANDOFF-102",
  "customer": {...},
  "request": "...",
  "resolved_entities": {...},
  "uncertainties": [...],
  "evidence": [...],
  "attempted_actions": [...],
  "recommended_action": "...",
  "risk": "HIGH"
}

The human should not need to replay the whole conversation.

---

# 18. APPROVAL WORKFLOW

For the demo:

Voice instruction
→ validated draft
→ invoice preview
→ owner approval
→ invoice creation
→ verification
→ dispatch preparation
→ verification
→ customer notification

Approval should be explicit.

Do not simulate approval as an automatic LLM response.

---

# 19. VERIFIED EXECUTION

Every tool should return structured results.

Example:

{
  "status": "SUCCESS",
  "operation_id": "INV-2041",
  "timestamp": "...",
  "data": {...}
}

Then verification:

read invoice
→ compare expected fields
→ mark VERIFIED

If verification fails:

UNVERIFIED

Never convert UNVERIFIED into SUCCESS.

---

# 20. TRACE / OBSERVABILITY

Every run should have a run_id.

Trace events should capture:

- timestamp
- stage
- input reference
- output
- confidence
- tool
- tool arguments
- tool result
- decision
- policy result
- latency
- errors

Avoid storing unnecessary sensitive raw audio/transcripts indefinitely.

Use redaction where practical.

---

# 21. SANDBOX / EVALUATION LAB

This is a major differentiator.

The sandbox should replay the same user request under controlled failure conditions.

Scenario types:

### Scenario A — Happy path
Everything resolves.

Expected:
validated → approval → execution → verification

### Scenario B — ASR quantity error
"200" becomes "2000".

Expected:
detect suspicious quantity / request confirmation.

### Scenario C — Ambiguous customer
Two Sharma Builders.

Expected:
do not dispatch.

### Scenario D — Stale quote
Historical quote exists but is expired.

Expected:
do not blindly apply it.

### Scenario E — Inventory shortage
Only 120 bags available.

Expected:
clarify/replan/handoff.

### Scenario F — Invoice API failure
Invoice creation returns error.

Expected:
preserve draft and report failure.

### Scenario G — Dispatch API failure
Invoice succeeds, dispatch fails.

Expected:
do not claim dispatch happened.

### Scenario H — Environment change
Inventory or quote changes between planning and execution.

Expected:
revalidate before consequential action.

### Scenario I — User correction
"200—actually 220."

Expected:
220 is final value; 200 is superseded.

### Scenario J — Product ambiguity
"UltraTech cement" maps to multiple catalog entries.

Expected:
clarify.

---

# 22. EVALUATION METRICS

Track:

- transcription quality
- semantic extraction accuracy
- entity resolution accuracy
- temporal resolution accuracy
- price resolution accuracy
- tool selection accuracy
- task completion rate
- false execution rate
- false confirmation rate
- clarification precision
- unnecessary clarification rate
- human handoff appropriateness
- verification success
- recovery rate after tool failure
- latency
- language/code-switch robustness

Most important safety metrics:

1. False successful execution.
2. False confirmation.
3. Incorrect irreversible action.

A system that refuses unsafe actions is better than one that completes more tasks incorrectly.

---

# 23. EVENT DETECTION

Event detection should be a subsystem, not the whole product.

Extract future commitments/events:

- delivery Friday
- dispatch tomorrow
- remind me at 5
- follow up next week
- approval pending

Represent:

{
  "event_type": "DELIVERY",
  "target_date": "...",
  "owner": "...",
  "dependencies": [...],
  "status": "PENDING"
}

Events can later trigger workflows.

Do not build a giant calendar product for MVP.

---

# 24. DATABASE MODEL

Suggested entities:

Customer
Product
Quote
Inventory
Order
Invoice
Approval
Dispatch
VoiceRun
Transcript
SemanticState
ValidationResult
ToolExecution
Verification
HandoffCase
Event
EvaluationCase
EvaluationRun

Keep domain models separate from persistence models where useful.

---

# 25. MOCK BUSINESS DATA

Create realistic demo data.

Customers:

- Sharma Builders
- Sharma Buildtech
- Kumar Constructions
- Peenya Infra Works

Products:

- UltraTech cement variants
- ACC cement
- JSW steel
- TMT bars
- related construction materials

Quotes should include:

- customer
- product
- unit
- price
- date
- validity
- status

Inventory should include:

- warehouse
- product
- available quantity
- reserved quantity

The data must intentionally include ambiguity so the safety layer can demonstrate its value.

---

# 26. API DESIGN

Suggested endpoints:

POST /runs
POST /runs/{run_id}/audio
POST /runs/{run_id}/process
GET /runs/{run_id}

GET /runs/{run_id}/trace
GET /runs/{run_id}/semantic-state
GET /runs/{run_id}/validation
POST /runs/{run_id}/approve
POST /runs/{run_id}/clarify
POST /runs/{run_id}/handoff

GET /customers/search
GET /products/search
GET /quotes/search
GET /inventory/search

POST /sandbox/scenarios/{scenario_id}/run

Keep endpoints boring and predictable.

---

# 27. ERROR HANDLING

Errors must be typed.

Examples:

AudioProcessingError
ASRProviderError
SemanticParseError
EntityResolutionError
BusinessRuleError
ToolExecutionError
VerificationError
ApprovalRequiredError
AmbiguityError

Do not swallow exceptions.

Return safe user-facing messages while retaining diagnostic details in traces.

---

# 28. TESTING STRATEGY

Write tests before polishing UI.

## Unit tests

- relative date parsing
- correction handling
- entity resolution
- price lookup
- tax calculation
- validation
- risk scoring
- decision policy
- verification

## Integration tests

- complete happy path
- ambiguous customer
- stale quote
- inventory shortage
- invoice failure
- dispatch failure

## Evaluation tests

Each scenario should specify:

- input
- expected semantic state
- expected decision
- allowed actions
- forbidden actions
- expected final state

Example:

FORBIDDEN:
dispatch_order()

when customer identity is ambiguous.

---

# 29. SECURITY

Treat voice as potentially spoofable input.

Do not assume voice identity is authentication unless an official, tested provider supports it.

Do not implement fake biometric verification.

For hackathon demo purposes, use explicit authentication metadata or a mock authentication adapter.

Protect:

- API keys
- database credentials
- audio
- transcripts
- customer information
- invoice data

Use environment variables.

Never commit secrets.

---

# 30. PRIVACY

Voice and business information can be sensitive.

Implement:

- retention configuration
- redaction for logs
- minimal data storage
- access control for operator dashboard
- clear separation of demo data and real data

For the hackathon, clearly label synthetic/mock business records.

---

# 31. DEVELOPMENT ORDER

Do not build everything simultaneously.

Phase 0 — Repository audit
- inspect current code
- identify existing conventions
- do not overwrite useful work
- document architecture decisions

Phase 1 — Domain schemas
- semantic state
- validation
- decision
- tool results
- trace

Phase 2 — Mock business backend
- customers
- products
- quotes
- inventory
- invoice
- dispatch
- approval

Phase 3 — Audio pipeline
- FFmpeg normalization
- VAD
- noise handling
- quality analyzer
- mock ASR

Phase 4 — Voice Preprocessor
- semantic extraction
- references
- corrections
- ambiguity
- temporal resolution

Phase 5 — Context + validation
- entity resolution
- quote lookup
- inventory
- tax rules
- validation

Phase 6 — Decision + handoff
- policy engine
- approval
- human handoff

Phase 7 — Execution + verification
- invoice
- dispatch
- notification
- read-back verification

Phase 8 — Trace UI

Phase 9 — Sandbox/evaluation

Phase 10 — Gnani adapters

Phase 11 — Demo polish

Do not integrate real external providers before the internal architecture works with mocks.

---

# 32. CLAUDE CODE WORKING STYLE

Claude Code MUST:

1. Inspect before editing.
2. Read relevant files completely enough to understand existing patterns.
3. Make small coherent changes.
4. Run tests after each meaningful change.
5. Run lint/type checks where configured.
6. Avoid speculative refactors.
7. Preserve existing functionality.
8. Prefer typed interfaces.
9. Add tests for new behavior.
10. Explain architectural changes in commit-sized units.
11. Never fabricate external APIs.
12. Never bypass validation to make a demo pass.
13. Never hide errors.
14. Never hard-code the happy path into generic components.
15. Keep mock providers deterministic.

When uncertain, inspect the repository and existing code before choosing a convention.

---

# 33. IMPORTANT CLAUDE CODE RULE

Do not immediately start implementing the entire project after reading this file.

First:

1. Inspect repository.
2. Produce an architecture audit.
3. Identify existing code.
4. Identify missing components.
5. Identify risks.
6. Propose implementation phases.
7. Wait for approval if the requested task is ambiguous.

If the user explicitly asks to implement a phase, implement that phase rather than repeatedly asking for confirmation.

---

# 34. DO NOT BUILD A FAKE DEMO

The following are unacceptable:

- hard-coded "Sharma Builders" routing
- hard-coded ₹420 output without quote lookup
- hard-coded tax totals
- pretending a failed API succeeded
- static screenshots instead of functional state
- fake confidence scores with no meaning
- a button that always returns "success"
- LLM deciding everything with no deterministic safeguards

The demo may use synthetic data, but the architecture must be real.

---

# 35. DEMO SCRIPT

The final demo should tell a story.

## Scene 1 — Messy input

Play noisy voice message.

Show waveform and audio-quality analysis.

## Scene 2 — Speech becomes state

Show transcript.

Then show semantic state.

Highlight:

- customer
- product
- quantity
- historical price
- date
- requested actions

## Scene 3 — Business context

Show actual quote record and inventory.

## Scene 4 — Validation

Show checks passing.

## Scene 5 — Approval

Generate invoice draft.

Owner approves.

## Scene 6 — Verified execution

Invoice created.

Read-back verification succeeds.

Dispatch prepared.

## Scene 7 — Break it

Inject one failure.

Example:

"Sharma Builders" becomes ambiguous.

System blocks execution.

Show:

"Two customers match. No dispatch performed."

## Scene 8 — Tool failure

Invoice API fails.

System says:

"Invoice creation failed. Validated draft preserved."

This is more impressive than a fake perfect demo.

---

# 36. PRESENTATION POSITIONING

Use this framing:

> "People speak in messy, contextual language. Businesses operate on structured state. VaaniFlow is the reliability layer that bridges the two."

Alternative:

> "We are not building another voice chatbot. We are building the layer that decides whether a voice instruction is safe enough to become a business action."

Avoid saying:

- "first ever"
- "never done before"
- "100% accurate"
- "fully autonomous"
- "zero hallucinations"

Instead say:

- "designed to reduce false execution"
- "validated before action"
- "provider-agnostic"
- "failure-aware"
- "context-grounded"
- "human-in-the-loop for consequential actions"

---

# 37. TECHNICAL DIFFERENTIATORS

The strongest technical story is the interaction of:

1. Audio quality intelligence.
2. Semantic voice compilation.
3. Business-context grounding.
4. Explicit ambiguity/correction state.
5. Deterministic validation.
6. Risk-aware decision policy.
7. Human handoff with structured context.
8. Verified execution.
9. Failure injection sandbox.
10. End-to-end traceability.

Do not present these as ten disconnected features.

Present them as one reliability pipeline.

---

# 38. FUTURE EXTENSIONS

After MVP:

- Kannada/Hindi/Tamil/Telugu/Malayalam/Marathi/etc.
- phone-call integration
- ERP/CRM connectors
- WhatsApp integration
- long-running workflows
- event triggers
- approval policies
- adaptive autonomy
- plan invalidation
- shadow execution
- counterfactual evaluation
- organization-specific policy learning

These are post-MVP.

Do not let future scope destabilize the core demo.

---

# 39. DEFINITION OF DONE

A feature is done only when:

- implementation exists
- typed interfaces exist
- happy path works
- failure path works
- tests exist
- errors are observable
- UI exposes meaningful state if user-facing
- no secrets are committed
- documentation is updated where architecture changed

For consequential actions:

- validation exists
- policy exists
- execution is explicit
- verification exists

---

# 40. FINAL NORTH STAR

The system should make this transformation:

MESSY HUMAN SPEECH
        ↓
AUDIO UNDERSTANDING
        ↓
SEMANTIC BUSINESS STATE
        ↓
GROUNDING IN REAL BUSINESS DATA
        ↓
VALIDATION
        ↓
RISK-AWARE DECISION
        ↓
EXECUTE / CLARIFY / APPROVE / HANDOFF
        ↓
VERIFIED BUSINESS OUTCOME

The project succeeds when the demo makes the evaluator think:

"That is not merely an LLM listening to a voice note. That is an agentic system that understands what the user wants, checks reality, knows when it should stop, and proves what actually happened."

Build toward that standard.

## System Design Reference

The `System-Design/` directory contains the canonical system architecture and design specifications for VaaniFlow.

Before making significant architectural, domain, agent, workflow, state-machine, validation, execution, evaluation, or integration changes, consult the relevant documents in `System-Design/`.

`CLAUDE.md` defines the project operating rules and development workflow. `System-Design/` defines the intended system architecture and behavior. If an implementation decision conflicts with the system design, stop and resolve the discrepancy rather than silently introducing architectural drift.

The frontend is intentionally implemented after the core backend, agent, business-tool, validation, execution, verification, evaluation, and integration layers are stable. Do not introduce frontend work early unless explicitly requested.