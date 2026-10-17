# UNDERSTAND → ACT handoff contract

The UNDERSTAND side produces exactly one object for the ACT side:
`vaaniflow.domain.schemas.understand.UnderstandResult` (schema `1.0`), which
embeds `SemanticState` (schema `2.0`). Both are strict Pydantic models
(`extra="forbid"`) and round-trip through JSON.

```text
Audio artifact → preprocessing → ASR → Transcript
  → SemanticCompiler → SemanticState
  → InputEvaluator   → InputEvaluation
  → UnderstandResult ──► ACT (context resolution, agent, validation, policy, ...)
```

Entry points (`vaaniflow.application.services.understand`):

- `UnderstandAudioService.execute(artifact=..., run_id=..., language_hint=...)`
- `UnderstandTranscriptService.execute(transcript=..., run_id=...)`

Stage failures raise typed port errors (`ArtifactStorageError`,
`AudioPreprocessorError`, `ASRProviderError`); no partial result is fabricated.

## What the result contains

| Field | Meaning |
|---|---|
| `transcript` | What the user said (provider-neutral; `provider_metadata` is opaque diagnostics) |
| `audio` | Original/processed artifact ids, measured processed-audio metadata, applied operations |
| `semantic_state` | What was understood (below) |
| `evaluation` | `actionability` + structured `reasons` (code, effect, slot, evidence, related ids) |

`SemanticState` slots:

| Slot | Notes |
|---|---|
| `intent`, `requested_actions[]` | Primary intent is the most consequential action; every action has recipient/channel where spoken |
| `customer`, `addressee` | Names **as spoken**. No customer ID. `addressee` is the employee being instructed ("Suresh") |
| `items[]` | Product mention bound to its quantity (`value`, canonical `unit`). One item per line |
| `pricing[]` | `SPOKEN` / `HISTORICAL_REFERENCE` / `SPOKEN_WITH_HISTORICAL_REFERENCE`; `item_id` binding; a spoken amount is a **claim to verify**, not a price |
| `tax` | Spoken instruction only ("plus GST" → `EXCLUSIVE`). No rate, no amount |
| `references[]` | `target_slot` says what they fill; `temporal_expression_id` links "same rate as parso" |
| `temporal_expressions[]` | Signed `day_offset` / weekday / explicit date parts. **Never a calendar date** unless the user spoke a full date (`ABSOLUTE`) |
| `corrections[]` | Superseded and corrected values; the slots already hold the corrected value |
| `ambiguities[]` | Semantic ambiguity only (ENTITY / VALUE / TEMPORAL / ACTION / REFERENCE / SCOPE) |

## Rules for the consumer

1. Resolve every business fact yourself: customer/product records, quotes,
   inventory, tax, and absolute dates (run clock + `Asia/Kolkata`).
2. `PARTIAL` means "understood; resolve the listed references". Each
   `CONTEXT_REFERENCE_UNRESOLVED` / `TARGET_ORDER_UNRESOLVED` reason names
   the reference id to resolve.
3. `CLARIFICATION_REQUIRED` and `BLOCKED` must not reach execution. The
   reasons say what to ask.
4. Business-context ambiguity (two "Sharma Builders" records) is yours to
   detect with `context.models.resolution.ResolutionStatus.AMBIGUOUS`; the
   semantic layer will never report it.
5. Confidence scores are rule-tier ordinals (`ConfidenceSource.RULE`), not
   calibrated probabilities; treat them as evidence, never as permission.
