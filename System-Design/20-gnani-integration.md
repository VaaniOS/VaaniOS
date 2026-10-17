# 20. Gnani Integration Strategy

## 20.1 Role of Gnani

Gnani technology is a core provider layer for voice interaction.

Expected architectural roles:

- Prisma: speech recognition
- Timbre: spoken response generation

Other Gnani capabilities should only be integrated when officially documented and available to the team.

## 20.2 Adapter boundary

```text
VaaniFlow
  │
  ├── ASRProvider
  │      ├── MockASR
  │      └── GnaniPrisma
  │
  └── TTSProvider
         ├── MockTTS
         └── GnaniTimbre
```

## 20.3 Provider-neutral domain

The following must never depend on Gnani-specific payload shapes:

- SemanticState
- ValidationResult
- AgentDecision
- ToolExecution
- Verification
- HandoffCase

## 20.4 Provider metadata

Provider responses can be retained under a provider-specific metadata field.

Do not let provider metadata become domain state.

## 20.5 Missing API documentation

If credentials/API documentation are unavailable:

- use mocks
- build exact adapter interfaces
- record integration assumptions
- do not invent endpoint names
- do not invent model versions
- do not claim latency/performance numbers

## 20.6 Integration test

The provider adapter should be replaceable without changing the domain tests.

Run:

```text
same SemanticState tests
same policy tests
same execution tests
different ASR/TTS provider
```

This validates the architecture.
