# 8. Validation, Policy and Risk

## 8.1 Separation

Three distinct concepts:

### Validation
"Is this state internally/business-wise valid?"

### Risk
"How dangerous is acting on this state?"

### Policy
"Given validity, risk and authorization, what are we allowed to do?"

Do not collapse all three into one LLM call.

## 8.2 Validation categories

Identity:
- customer
- recipient
- product

Quantitative:
- quantity
- unit
- inventory

Financial:
- unit price
- quote
- tax
- total
- deviation

Operational:
- warehouse
- dispatch capability
- duplicate order

Authorization:
- approval
- user permissions

## 8.3 Severity

- INFO
- WARNING
- HIGH
- CRITICAL

A HIGH issue can require clarification.
A CRITICAL issue should block execution.

## 8.4 Risk score

Recommended normalized score:

`0.0 – 1.0`

Possible inputs:

```text
semantic_uncertainty
entity_ambiguity
financial_exposure
irreversibility
external_side_effect
data_sensitivity
policy_violation
tool_reliability
```

Use a transparent weighted model initially.

## 8.5 Policy matrix

Example:

| Condition | Decision |
|---|---|
| Fully validated, low-risk read | EXECUTE |
| Validated but financial write | APPROVAL_REQUIRED |
| Minor ambiguity, reversible | CONFIRM |
| Critical identity ambiguity | CLARIFY |
| Conflicting business records | HUMAN_HANDOFF |
| Policy violation | BLOCKED |
| Tool failure | FAILED / PRESERVE STATE |

## 8.6 Explainability

Every decision should have machine-readable reasons.

Example:

```json
{
  "decision": "BLOCKED",
  "reasons": [
    {
      "code": "AMBIGUOUS_CUSTOMER",
      "severity": "HIGH"
    },
    {
      "code": "IRREVERSIBLE_DISPATCH",
      "severity": "HIGH"
    }
  ]
}
```

The UI turns these into human-readable explanations.

## 8.7 Confirmation vs clarification

Clarification asks:

"What did you mean?"

Confirmation asks:

"I understood X. Do you want me to proceed?"

Use clarification when the system lacks information.
Use confirmation when the system has a candidate interpretation but wants explicit authorization.
