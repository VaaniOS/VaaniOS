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
| `ambiguities[]` | Semantic ambiguity only (ENTITY / VALUE / TEMPORAL / ACTION / REFERENCE / SCOPE). Offered alternatives ("UltraTech ya ACC", "200 ya 300") appear here with every candidate; the slot itself stays empty |
| `negated_actions[]` | Actions the user explicitly said **not** to perform ("don't dispatch", "dispatch mat karo"). Never execute these |

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
6. Never execute anything listed in `negated_actions`, and never pick one
   candidate from an ambiguity's `candidates` on the user's behalf.
7. A historical price is anchored through the links, not by position:
   `pricing[].reference_id` → `references[].temporal_expression_id` →
   `temporal_expressions[]`. ACT resolves that expression against the transcript's
   `created_at` (when the user spoke) and only matches quotes given on that date
   (System-Design 06 §6.6). A temporal expression with no such link (e.g. an
   execution date, `target = EXECUTION`) never constrains quote selection.

## Known limitations

These are not supported yet; ACT must not assume otherwise.

- **Devanagari transcripts** are not interpreted. They compile to an empty
  UNKNOWN state and evaluate to BLOCKED, never to wrong facts.
- **Irregular Hindi number words** for 21–99 (e.g. "pachchis") are not
  parsed; the quantity is then missing and evaluation asks for it. Units
  1–19, tens, "sau"/"hazaar"/"lakh" and "dedh"/"dhai" are supported.
- **Hedged quantities** ("around 200", "lagbhag 200") are kept as the stated
  value; the hedge is not represented. Treat quantities as exact claims to
  be confirmed by ACT policy.
- **Audio formats: only WAV is covered by tests.** The local preprocessor
  decodes through soundfile/libsndfile and always outputs 16 kHz mono PCM16
  WAV. In the verified environment (libsndfile 1.2.2) it also decoded FLAC,
  Ogg Vorbis, Ogg Opus (WhatsApp) and MP3, but these paths have no automated
  tests. M4A/AAC is not supported. No VAD trimming, denoising or enhancement
  is done.
- **The live Gnani API is not exercised** by repository tests; the adapter
  is tested against a fake SDK client. Language/ITN defaults are unverified.
- **No ASR confidence** is propagated (the Gnani REST response has none);
  all semantic confidence is rule-tier and ordinal.
- **Unknown products** without a known category noun are taken positionally
  ("200 bags Birla Gold") at confidence 0.55 and must be resolved by ACT.
- **Negation coverage** is limited to the listed English/Hinglish forms;
  "or else" constructions such as "dispatch karo nahi to …" are
  conservatively treated as negation (non-actionable).
- **Unusable audio** still reaches ASR; Input Evaluation then blocks it.
- **No event/commitment extraction** (System-Design 21).
