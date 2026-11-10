# 18. Architecture Decisions

## ADR-001 — Modular monolith for MVP

Decision:
Use a modular monolith with optional worker.

Reason:
Fast iteration, clear module boundaries, less operational overhead.

Rejected:
Many microservices.

## ADR-002 — Semantic state between ASR and agent

Decision:
Introduce a typed SemanticState.

Reason:
Prevents raw transcript from becoming business action and creates a stable contract between teammates.

## ADR-003 — Business facts come from tools

Decision:
Customer/product/quote/inventory/tax/execution facts must be grounded.

Reason:
LLM memory is not authoritative business state.

## ADR-004 — Deterministic policy boundary

Decision:
LLM proposes; validation and policy constrain.

Reason:
Consequential actions require predictable safeguards.

## ADR-005 — Provider adapters

Decision:
Gnani integrations remain behind interfaces.

Reason:
Protect domain architecture from undocumented or changing provider APIs and enable mocks.

## ADR-006 — Verification after writes

Decision:
Read back important state after execution.

Reason:
Tool acknowledgement does not always prove business state.

## ADR-007 — Failure injection sandbox

Decision:
Build replayable controlled failures into the product.

Reason:
The differentiator is reliability under realistic failure, not only happy-path completion.

## ADR-008 — Structured handoff

Decision:
Escalation creates a context-rich case.

Reason:
A human should not need to reconstruct the conversation.

## ADR-009 — Synthetic business data

Decision:
Use synthetic records for the hackathon.

Reason:
No external ERP dependency and safe reproducibility.

## ADR-010 — Explicit approval

Decision:
Financial/consequential operations require explicit approval where policy says so.

Reason:
Authorization must not be inferred from conversational intent alone.

## ADR-011 — Original audio preservation

Decision:
Never overwrite raw audio.

Reason:
Required for debugging preprocessing and ASR failures.

## ADR-012 — Corrections are events

Decision:
Represent old and new values with supersession.

Reason:
Auditability and correct semantic state.

## ADR-013 — Input Evaluation stage and UnderstandResult handoff

Decision:
Actionability is assessed by a dedicated deterministic Input Evaluation stage (`vaaniflow.semantic.evaluation.InputEvaluator`) that runs after the semantic compiler. `SemanticState` no longer carries `actionability`; it travels in `InputEvaluation` together with structured reasons (code, effect, slot, evidence). The UNDERSTAND side hands off a single `UnderstandResult` (transcript + audio provenance + SemanticState + InputEvaluation) to the ACT side.

Definitions:
- COMPLETE — every required slot is stated and coherent.
- PARTIAL — understood, but a reference ("same rate", "that order", "it") must be resolved by context.
- CLARIFICATION_REQUIRED — the user must supply or disambiguate something.
- BLOCKED — not an actionable request (or the audio is unusable).

Reason:
05 §5.8 lists actionability as a compiler responsibility, but the agreed team split makes Input Evaluation an UNDERSTAND deliverable with its own evidence. Separating "extract" from "assess" keeps the compiler free of policy-like judgement and gives ACT machine-readable reasons. This is semantic completeness only; it never consults business data and does not replace validation/policy (08).

## ADR-014 — Orientation of bidirectional Hindi day words

Decision:
"kal" (±1), "parso" (±2) and "narso" (±3) are oriented by deterministic linguistic evidence in the compiler: (1) a temporal expression that qualifies a historical reference ("rate wahi jo parso bataya tha", "same rate as parso") is PAST; (2) otherwise the nearest tense cue in the same sub-clause decides ("bataya tha" → PAST, "dispatch karo" → FUTURE); (3) a correction inherits the corrected expression's direction. Without evidence the expression stays AMBIGUOUS and produces a TEMPORAL_AMBIGUITY. The evidence is stored in `direction_evidence`.

The compiler emits only a signed day offset; turning it into a calendar date (run clock, business timezone, calendar) remains the context layer's job (06 §6.5, CLAUDE.md §11). `TemporalExpression.resolved_datetime` was removed from the semantic contract.

Reason:
The canonical scenario needs "parso" to mean two days ago without letting an LLM or the compiler invent dates. Tense is linguistic information that only the semantic layer sees.

## ADR-015 — SemanticState 2.0 typed slots

Decision:
`SemanticState` (schema_version "2.0") replaces the flat `entities` / `quantities` / `constraints` lists with typed slots:
`customer`, `addressee`, `items[]` (product mention bound to its quantity), `pricing[]` (spoken amount and/or historical reference, currency, per-unit, item binding), `tax` (spoken tax instruction), slot-targeted `references[]` (linked to items and temporal anchors), structured `temporal_expressions[]`, typed `corrections[]` with superseded and corrected values, `ambiguities[]` using the 05 §5.7 classes, `requested_actions[]` with recipient/channel, `run_id`, character spans and compiler provenance.

Business-context ambiguity types (ambiguous customer record, ambiguous quote) are not part of the semantic ambiguity enum; they belong to `context.models.resolution.ResolutionStatus.AMBIGUOUS`. Missing information is an Input Evaluation reason, not an ambiguity.

Reason:
Flat lists forced the ACT side to guess which quantity belonged to which product and which "same rate" applied to what. Confidence remains per object (rule-tier, ordinal; see `semantic/confidence.py`).

## ADR-016 — Write-once artifact storage and processed-artifact lineage

Decision:
`ArtifactStorage.store` is write-once (`ArtifactAlreadyExistsError`). Processed artifacts are stored at `local://processed/<artifact_id>.wav` and `AudioPreprocessingResult` records `source_artifact_id` and `applied_operations`. Processed-artifact quality metadata is measured (`vaaniflow.audio.quality`), not copied from the caller.

Reason:
Enforces ADR-011 (never overwrite original audio) and 04 §4.3 (original and processed artifacts preserved separately with metadata).

## ADR-017 — Gnani speech-to-text adapter

Decision:
The ASR adapter uses the installed `gnani-vachana` SDK (`gnani.stt.GnaniSTTClient.transcribe_bytes`). It sends a filename hint derived from the artifact MIME type, maps SDK/network/configuration errors to typed `ASRProvider*Error`s, rejects `success: false`, keeps documented response metadata as opaque `Transcript.provider_metadata`, and leaves `detected_languages` empty because the REST response reports no language detection.

Assumption (unverified without credentials):
This SDK is the product referred to as "Prisma" in CLAUDE.md/20. Default `format="verbatim"` returns spoken-form numbers, which the compiler parses for romanised Hindi/English; Devanagari output is not yet supported by the compiler.

## ADR-018 — Negated actions and offered alternatives

Decision:
1. Negation is bound to an action cue inside its sub-clause (never a global flag): English "don't / do not / never <verb>", Hinglish "<verb> mat/nahi/nahin …" or "mat/nahi <verb>". A negated cue is recorded in `SemanticState.negated_actions`, never in `requested_actions`, and Input Evaluation adds a `NEGATED_ACTION` reason (CLARIFICATION_REQUIRED; BLOCKED when nothing else was said). An action both requested and negated is an ACTION_AMBIGUITY. Correction markers (", nahi nahi,", "not tomorrow") are separated by punctuation and are not treated as negation.
2. Alternatives introduced by "ya" / "or" ("UltraTech ya ACC cement", "200 ya 300 bags", "Sharma ya Kumar ko", "400 ya 420 rupaye") are never resolved to one value. The slot stays empty and an ENTITY_AMBIGUITY (product/customer) or VALUE_AMBIGUITY (quantity/price) lists every candidate.

`negated_actions` was added to SemanticState 2.0 before the contract was first published, so `schema_version` stays "2.0".

Reason:
"don't dispatch" ≠ dispatch, "UltraTech ya ACC" ≠ one product, "200 ya 300" ≠ 300. The semantic layer must surface these explicitly instead of producing a confident COMPLETE state.

## ADR-019 — Pricing authority: a spoken price is a claim

Decision:
The execution unit price is the price of exactly one quote for the resolved customer and product that is applicable on the business date: status VALID and `quoted_on ≤ business date ≤ valid_until` (inclusive; no `valid_until` means open-ended). A spoken amount is compared with that quote; a mismatch requires confirmation. A historical reference ("rate wahi jo parso bataya tha") only matches quotes given on the date of the temporal expression linked to the reference the price points to (`pricing[].reference_id`); no other date is substituted. An undated reference ("same rate") uses the single applicable quote. If no applicable quote exists, nothing is executable: a spoken price without a quote goes to human handoff; a referenced rate with no quote on its date, or with several, is clarified; a referenced quote that exists but is no longer applicable goes to human handoff with the quote kept as evidence; a request with no pricing at all is blocked. `ACCEPTED` quotes are not executable pricing because the model does not define their semantics.

This is the current business policy, not a permanent one. The catalog has no list prices, so a customer without a quote cannot be sold to by voice until an operator prices the request. A future catalog or operator-pricing source must be added as an explicit authority, never as a fallback.

Reason:
Business facts come from records (ADR-003). Treating whatever amount was heard ("₹1 per bag", or an ASR error) as authoritative would let speech set prices.

## ADR-020 — Explicit business clock

Decision:
Relative dates resolve against the time the user spoke, and quote validity against the business date of execution, both from the orchestrator's injectable clock. Production uses the real clock. A fixed clock is only ever explicit: the evaluation runner runs scenarios at `SYNTHETIC_BUSINESS_TIME` (the synthetic dataset's 2026-10-17 12:00 IST), and the API uses a fixed clock only when `VAANIFLOW_BUSINESS_CLOCK` is set (`synthetic` or a timezone-aware ISO-8601 instant). Approval re-assessment keeps the original utterance time, so "parso" does not move when approval happens on a later day.

Reason:
Quote validity and "parso" are only meaningful relative to a business date. Demos and evaluation must be deterministic without hard-coding dates into temporal resolution or weakening production behaviour.

## ADR-021 — Follow-up, duplicate and audit semantics (P2)

Decision:
1. Duplicate orders are detected deterministically on business identity (customer, currency, line items with unit price, delivery address when both sides have one). An equivalent open order blocks a new one whenever it was placed; an equivalent completed (fulfilled or dispatched) order blocks only on the same business date; cancelled and failed orders never block. The check runs before approval is requested and again at execution. If existing orders cannot be read, no order is created (handoff).
2. A CONFIRM decision creates a confirmation bound to its run, the exact warnings (`check_type|field|expected|actual`) and the business snapshot. A reply is classified deterministically as yes / no / unclear; only "yes" to a still-pending confirmation of the same run accepts exactly those warnings, and approval is still required afterwards. Changed facts expire it; a new instruction supersedes it.
3. An UNKNOWN execution can be resolved by an operator only for the exact run, execution and attempt. SUCCEEDED requires a record stamped with that operation's idempotency key that passes read-back verification; FAILED is refused if such a record exists. The UNKNOWN history (`prior_*`) and the resolution (`resolution`, `resolved_by`, `resolved_at`, `resolution_reason`) are kept on the execution. Resolution never runs the remaining steps.
4. Approvals record run, plan id and fingerprint, requested and approval-time snapshots, actors, timestamps, rejection and expiry reasons, `superseded_by`, and the records the plan produced. No identity is fabricated. (Superseded for identity by ADR-022: actors are now authenticated principals.)
5. Clarifications are persisted with what was understood and what is unresolved (evaluation reasons, ambiguities with candidates, failed checks); a new instruction supersedes them. (Partial replies: see ADR-023.)

Reason:
Technical idempotency prevents a retried call from writing twice, not a second identical request from creating a second order. A "yes" must never approve something other than what was shown, an operator must not be able to declare success for a write that never happened, and the audit trail must answer what was approved, by whom, and what actually happened.

## ADR-022 — One verified authentication and authorization model

Decision:
1. Identity comes only from a verified credential. The HTTP API reads `Authorization: Bearer <token>` and maps it to a `Principal` (actor id, display name, roles, authentication method) through an injectable `IdentityProvider`. The default provider reads an explicit token map from `VAANIFLOW_API_TOKENS`; unset means no principals (every protected route answers 401) and a malformed map fails at startup. No other header is read: `X-Role`, `X-User-Id` and `X-Principal-Id` have no effect, and no token format (e.g. `operator:<name>`, a bare UUID) asserts an identity or role.
2. Authorization is a separate decision per permission: `SUBMIT_INSTRUCTION` → REQUESTER/OWNER/OPERATOR; `APPROVE` (approve and reject) → OWNER; `CONFIRM` → REQUESTER/OWNER; `RESOLVE_UNKNOWN`, `CREATE_HANDOFF` → OPERATOR; `READ_AUDIT` → AUDITOR/OPERATOR/OWNER. The API checks it, and the orchestrator checks approve, reject, confirm, UNKNOWN resolution and escalation again, so an adapter that calls the orchestrator directly cannot bypass it.
3. Runs are owned by the authenticated principal that created them. Only the owner (or an OPERATOR) may add an instruction; a REQUESTER may confirm only their own run; the owner or a READ_AUDIT holder may read the run and its trace. The OWNER approves runs requested by others — that is the role's purpose. Escalated (`HANDOFF`) and settled (`EXECUTING`, `COMPLETED`, `PARTIALLY_COMPLETED`, `FAILED`, `BLOCKED`) runs take no new instruction (409). These rules live in `application/services/run_access.py` for every adapter.
4. Records keep the principal that acted (`approved_actor`, `rejected_actor`, `confirmed_actor`, `resolved_actor`). `actor_authenticated` is true only when the approver or rejecter was authenticated by a credential; it is false while an approval is pending and for the labelled synthetic evaluation actor. Request bodies carry no identity field (extra fields → 422).
5. Escalation (`POST /runs/{id}/handoff`, OPERATOR) supersedes every pending approval, confirmation and clarification on the run before handing it to the escalating operator.
6. Other adapters map their users to principals through their own explicit, configured identity provider and then use the same checks. The Telegram adapter uses `TELEGRAM_PRINCIPALS` (numeric Telegram user id → principal, `authentication_method = "telegram-allowlist"`); unknown users, group chats and senders that are not the chat are refused; callback data is parsed against a fixed grammar and never carries identity; instructions go through `authorize_instruction`, and approve/reject/confirm through the orchestrator's permission and ownership checks.

Reason:
Identity asserted by a caller (a header, a role-named token, a body field) is not authentication, and an approval recorded under such an identity proves nothing. One model, enforced at the API and again in the orchestrator, keeps every adapter on the same rules. Static tokens are a sandbox credential store; the `IdentityProvider` boundary lets a real identity provider replace it.

## ADR-023 — Telegram as a truthful projection of application state

Decision:
1. Telegram renders only what the backend returned (`presentation/telegram_views.py`): approval cards from the run's SemanticState, BusinessContext, validation checks, risk, tax calculation and plan; receipts from per-step `StepStatus` with headers derived from the run status (complete only when every step is VERIFIED; partial, UNKNOWN and handoff stated explicitly); benchmark and status from the evaluation runner and repositories. Every dynamic value is HTML-escaped.
2. The bot uses the API's application container by default; `python -m vaaniflow.presentation.serve` runs both in one process so runs, approvals and audits are shared. State stays in memory (prototype).
3. Voice notes go Telegram audio → FFmpeg (configurable executable, timeout, sanitized errors) → write-once ingest → preprocessing → the configured ASR adapter → `process_transcript`, which keeps the provider's transcript and feeds measured audio quality to Input Evaluation. A failure at any stage creates no run; no other text is ever substituted.
4. A clarification reply is compiled by the unchanged UNDERSTAND compiler and merged only into the slots the open clarification asked for (customer, product, quantity), into a new transcript (original + reply) whose spans stay valid; the merged state is re-evaluated and goes through the normal ACT pipeline. A reply naming actions is a new instruction; one that answers nothing asked, adds other facts, or contradicts what was understood changes nothing.

Reason:
A demo interface that shows fixed values, or success for steps that did not happen, undermines the system's central claim. The UI must be a view of the same state the API audit reports.
