# 22. Repository Blueprint

Recommended:

```text
/
├── CLAUDE.md
├── README.md
├── .env.example
├── docker-compose.yml
├── Makefile
│
├── apps/
│   ├── api/
│   │   ├── src/vaaniflow/
│   │   │   ├── api/
│   │   │   ├── domain/
│   │   │   │   ├── models/
│   │   │   │   ├── schemas/
│   │   │   │   └── policies/
│   │   │   ├── application/
│   │   │   ├── infrastructure/
│   │   │   ├── providers/
│   │   │   ├── audio/
│   │   │   ├── semantic/
│   │   │   ├── context/
│   │   │   ├── agent/
│   │   │   ├── validation/
│   │   │   ├── execution/
│   │   │   ├── handoff/
│   │   │   ├── traces/
│   │   │   └── evaluation/
│   │   └── tests/
│   │
│   ├── web/
│   │   ├── app/
│   │   ├── components/
│   │   ├── lib/
│   │   └── types/
│   │
│   └── worker/
│
├── packages/
│   ├── schemas/
│   ├── mock-business/
│   └── evaluation-cases/
│
├── data/
│   ├── customers/
│   ├── products/
│   ├── quotes/
│   ├── inventory/
│   └── scenarios/
│
├── docs/
│   ├── architecture/
│   ├── decisions/
│   └── demo/
│
└── scripts/
```

## Module responsibilities

### `audio/`
Audio artifact handling and preprocessing.

### `semantic/`
Semantic compiler and schema validation.

### `context/`
Business grounding and resolution.

### `agent/`
Agent loop, planning and tool selection.

### `validation/`
Business checks.

### `execution/`
Side-effecting operations and verification.

### `handoff/`
Escalation.

### `traces/`
Run event recording.

### `evaluation/`
Sandbox and scoring.

## Avoid

- giant `utils.py`
- business logic in route handlers
- provider calls inside domain models
- frontend directly calling external providers
- LLM prompts scattered across random files
- hidden global state
