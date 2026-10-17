# 3. Data Model

## 3.1 Design principles

- Domain state is typed.
- External provider payloads are stored separately from canonical state.
- Provenance is attached to important facts.
- State transitions are explicit.
- Historical values are immutable where auditability matters.
- Synthetic data must be clearly identifiable.

## 3.2 Core entities

### Customer

Fields:
- customer_id
- legal_name
- display_name
- aliases
- phone numbers
- addresses
- tax identifiers if required by demo
- status
- created_at
- updated_at

### Product

Fields:
- product_id
- SKU
- brand
- product_name
- category
- aliases
- unit
- packaging
- active

### Quote

Fields:
- quote_id
- customer_id
- product_id
- quoted_unit_price
- currency
- unit
- quoted_at
- valid_until
- status
- source
- created_by

### Inventory

Fields:
- inventory_id
- warehouse_id
- product_id
- available_quantity
- reserved_quantity
- version
- updated_at

### Order

Fields:
- order_id
- customer_id
- items
- source_run_id
- status
- approval_id
- created_at

### Invoice

Fields:
- invoice_id
- order_id
- customer_id
- line_items
- tax_breakdown
- totals
- status
- version
- created_at

### Approval

Fields:
- approval_id
- target_type
- target_id
- requested_by
- approved_by
- status
- requested_at
- decided_at
- evidence_snapshot

### Dispatch

Fields:
- dispatch_id
- order_id
- warehouse_id
- recipient
- status
- created_at

## 3.3 VoiceRun

Represents one user interaction.

Fields:
- run_id
- source
- original_audio_uri
- processed_audio_uri
- status
- started_at
- completed_at
- locale
- correlation_id

## 3.4 Transcript

Fields:
- transcript_id
- run_id
- text
- segments
- language
- code_switches
- provider
- provider_metadata
- confidence if available

## 3.5 SemanticState

Fields:
- semantic_state_id
- run_id
- schema_version
- intent
- entities
- constraints
- temporal_references
- corrections
- ambiguities
- requested_actions
- confidence
- actionability
- created_at

> Amended by ADR-013 / ADR-015: SemanticState 2.0 carries typed slots and no
> `actionability`; see `vaaniflow.domain.schemas.semantic` and
> `vaaniflow.domain.schemas.understand`.

## 3.6 Provenance

Every important resolved fact should identify:

```text
fact
source_type
source_id
retrieved_at
resolver
confidence
evidence
```

Example:

```json
{
  "fact": "unit_price=420",
  "source_type": "QUOTE",
  "source_id": "Q-1092",
  "retrieved_at": "2026-10-17T12:00:00+05:30",
  "resolver": "historical_quote_resolver"
}
```

## 3.7 ValidationResult

Fields:
- validation_id
- run_id
- status
- checks
- blocking_issues
- warnings
- risk_score
- policy_version

## 3.8 ToolExecution

Fields:
- execution_id
- run_id
- tool_name
- operation
- idempotency_key
- arguments_hash
- started_at
- completed_at
- status
- provider_result
- error_code

## 3.9 Verification

Fields:
- verification_id
- execution_id
- expected_state
- observed_state
- comparison
- status
- verified_at

## 3.10 HandoffCase

Fields:
- case_id
- run_id
- reason
- priority
- context_snapshot
- evidence
- attempted_actions
- recommended_action
- assigned_to
- status

## 3.11 EvaluationCase

Fields:
- case_id
- scenario_type
- input
- injected_faults
- expected_semantic_state
- expected_decision
- allowed_actions
- forbidden_actions
- expected_final_state

## 3.12 State immutability

Do not overwrite historical semantic/decision records.

If the user corrects 200 to 220:

```text
Value 200
   ↓ superseded_by
Value 220
```

The current state becomes 220, but the trace retains the correction event.
