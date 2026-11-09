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
The execution unit price is the price of exactly one quote for the resolved customer and product that is applicable on the business date: status VALID and `quoted_on ≤ business date ≤ valid_until` (inclusive; no `valid_until` means open-ended). A spoken amount is compared with that quote; a mismatch requires confirmation. A historical reference ("rate wahi jo parso bataya tha") only matches quotes given on the date of the temporal expression linked to it; no other date is substituted. If no applicable quote exists, nothing is executable: a spoken price without a quote goes to human handoff, a referenced rate without a matching quote is clarified.

This is the current business policy, not a permanent one. The catalog has no list prices, so a customer without a quote cannot be sold to by voice until an operator prices the request. A future catalog or operator-pricing source must be added as an explicit authority, never as a fallback.

Reason:
Business facts come from records (ADR-003). Treating whatever amount was heard ("₹1 per bag", or an ASR error) as authoritative would let speech set prices.

## ADR-020 — Explicit business clock

Decision:
Relative dates resolve against the time the user spoke, and quote validity against the business date of execution, both from the orchestrator's injectable clock. Production uses the real clock. A fixed clock is only ever explicit: the evaluation runner runs scenarios at `SYNTHETIC_BUSINESS_TIME` (the synthetic dataset's 2026-10-17 12:00 IST), and the API uses a fixed clock only when `VAANIFLOW_BUSINESS_CLOCK` is set (`synthetic` or a timezone-aware ISO-8601 instant). Approval re-assessment keeps the original utterance time, so "parso" does not move when approval happens on a later day.

Reason:
Quote validity and "parso" are only meaningful relative to a business date. Demos and evaluation must be deterministic without hard-coding dates into temporal resolution or weakening production behaviour.
