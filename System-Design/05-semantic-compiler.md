# 5. Semantic Voice Compiler

## 5.1 Purpose

The semantic compiler converts probabilistic language into typed intermediate representation.

It is analogous to a compiler frontend:

```text
Speech
→ tokens/utterance
→ semantic interpretation
→ intermediate representation
→ validated executable intent
```

It is NOT merely a JSON extractor.

## 5.2 Responsibilities

- intent classification
- entity extraction
- reference detection
- temporal expression extraction
- corrections
- constraints
- requested actions
- ambiguity identification
- confidence estimation
- actionability classification

## 5.3 Intermediate representation

Original v1 sketch, kept for history. **It is not the current contract**:
the implemented SemanticState 2.0 is defined by ADR-015 / ADR-018 and
`vaaniflow.domain.schemas.semantic`, and actionability moved to Input
Evaluation (ADR-013).

```json
{
  "schema_version": "1.0",
  "intent": {},
  "entities": [],
  "items": [],
  "constraints": [],
  "references": [],
  "temporal_references": [],
  "corrections": [],
  "ambiguities": [],
  "requested_actions": [],
  "confidence": {},
  "actionability": "PARTIAL"
}
```

> Implemented as SemanticState 2.0 — see ADR-015 for the typed slot layout
> (`items`, `pricing`, `tax`, slot-targeted `references`) and ADR-018 for
> `negated_actions` and offered alternatives.

## 5.4 Confidence must be contextual

Do not use one global confidence number as truth.

Track confidence per:

- customer
- product
- quantity
- price
- date
- action

Example:

```json
{
  "customer": 0.91,
  "product": 0.78,
  "quantity": 0.99,
  "price_reference": 0.65
}
```

A low confidence in a low-impact descriptive phrase may be harmless.
A low confidence in quantity or customer identity can be blocking.

## 5.5 Corrections

Recognize patterns such as:

- "no, actually..."
- "I mean..."
- "sorry..."
- "make that..."
- "not X, Y"
- "200—actually 220"

Represent:

```json
{
  "field": "quantity",
  "old_value": 200,
  "new_value": 220,
  "reason": "USER_CORRECTION"
}
```

## 5.6 References

Examples:

- "same customer"
- "that product"
- "the previous quote"
- "the usual rate"
- "the one we sent yesterday"

Do not resolve these purely from language. Emit a reference and let the context layer resolve it.

## 5.7 Ambiguity classes

- ENTITY_AMBIGUITY
- VALUE_AMBIGUITY
- TEMPORAL_AMBIGUITY
- ACTION_AMBIGUITY
- REFERENCE_AMBIGUITY
- SCOPE_AMBIGUITY

## 5.8 Actionability

Suggested states:

- COMPLETE
- PARTIAL
- CLARIFICATION_REQUIRED
- BLOCKED

Actionability is not the same as confidence.

> Amended by ADR-013: actionability is assessed by the Input Evaluation stage
> after compilation and travels in `InputEvaluation` / `UnderstandResult`.

## 5.9 LLM boundary

The model can propose semantic state.

A schema validator must reject malformed state.

Business tools must validate business facts.

Policy must determine allowed actions.

## 5.10 Example

Input:

"Send 200—actually 220 bags to Sharma Builders, same rate as parso."

Compiler output:

- quantity = 220
- correction = 200 → 220
- customer_reference = Sharma Builders
- price_reference = historical
- date_reference = parso

It should NOT output a final quote ID or customer ID unless those came from context resolution.
