"""
Phase 3 — the Telegram UI is a projection of actual VaaniFlow state.

Only external boundaries are replaced: the Telegram API (MockTelegramClient), the
ASR provider (MockASR / failing stubs) and, where stated, the FFmpeg conversion.
Everything else is the real application pipeline.
"""

from __future__ import annotations

import asyncio
import io
import re
import shutil
import stat
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from tests.auth_support import AUDITOR, auth, provider
from tests.integration.test_telegram_bot import MockTelegramClient
from vaaniflow.api.app import app
from vaaniflow.api.dependencies import reset_container
from vaaniflow.application.ports.asr import ASRProviderUnavailableError
from vaaniflow.application.schemas.asr import ASRInput
from vaaniflow.application.services.orchestrator import VoiceWorkflowOrchestrator, WorkflowResult
from vaaniflow.application.services.voice_intake import VoiceIntakeError, VoiceIntakeService
from vaaniflow.audio import LocalAudioPreprocessor
from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.principal import Principal, Role
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.domain.schemas.transcript import Transcript
from vaaniflow.evaluation.models import (
    ScenarioEvaluationResult,
    ScenarioId,
    SuiteEvaluationResult,
)
from vaaniflow.execution.plan import StepOutcome, StepStatus
from vaaniflow.infrastructure.audio import ffmpeg
from vaaniflow.infrastructure.audio.ffmpeg import AudioConversionError, convert_to_pcm16_wav
from vaaniflow.infrastructure.repositories.synthetic_data import (
    SYNTHETIC_BUSINESS_TIME,
    SyntheticRepositories,
)
from vaaniflow.infrastructure.storage.local import LocalArtifactStorage
from vaaniflow.presentation import telegram_bot, telegram_views
from vaaniflow.presentation.telegram_bot import VaaniFlowTelegramBot
from vaaniflow.presentation.telegram_security import TelegramIdentityProvider
from vaaniflow.providers.mock import MockASR

T = SYNTHETIC_BUSINESS_TIME
USER = 42
OWNER = Principal(
    principal_id=UUID("00000000-0000-4000-8000-00000000d042"),
    display_name="Demo Owner",
    roles=[Role.OWNER, Role.REQUESTER],
    authentication_method="telegram-allowlist",
)
KUMAR = "Kumar Constructions ko 10 bags ACC cement ₹400 per bag dispatch karo."
KUMAR_15 = "Kumar Constructions ko 15 bags ACC cement ₹400 per bag dispatch karo."
SHARMA_150 = (
    "Sharma Builders ko 150 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
    "Invoice bana do."
)
CANONICAL = VaaniFlowTelegramBot.CANONICAL_DEMO_TEXT
ALLOWED_TAGS = {"b", "i", "code"}


def _bot(**kwargs: Any) -> tuple[VaaniFlowTelegramBot, MockTelegramClient]:
    client = MockTelegramClient()
    kwargs.setdefault("repositories", SyntheticRepositories())
    bot = VaaniFlowTelegramBot(
        token="test_token",
        client=client,
        identity=TelegramIdentityProvider({USER: OWNER}),
        **kwargs,
    )
    return bot, client


def _msg(text: str = "", **extra: Any) -> dict[str, Any]:
    message = {
        "message_id": 1,
        "chat": {"id": USER, "type": "private"},
        "from": {"id": USER, "first_name": "Owner"},
        "text": text,
        **extra,
    }
    return {"update_id": 1, "message": message}


def _click(data: str) -> dict[str, Any]:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "q",
            "data": data,
            "from": {"id": USER, "first_name": "Owner"},
            "message": {"message_id": 5, "chat": {"id": USER, "type": "private"}},
        },
    }


def _send(bot: VaaniFlowTelegramBot, update: dict[str, Any]) -> None:
    asyncio.run(bot.handle_update(update))


def _last(client: MockTelegramClient) -> str:
    return str(client.sent_messages[-1]["text"])


def _button(client: MockTelegramClient, verb: str) -> str:
    for message in reversed(client.sent_messages):
        for row in (message.get("reply_markup") or {}).get("inline_keyboard", []):
            for button in row:
                if button["callback_data"].startswith(f"{verb}:"):
                    return str(button["callback_data"])
    raise AssertionError(f"no {verb} button")


def _tags(text: str) -> set[str]:
    return set(re.findall(r"</?([a-zA-Z][a-zA-Z0-9]*)", text))


def _pending(bot: VaaniFlowTelegramBot) -> Any:
    run_id = bot.active_runs[OWNER.principal_id]
    return bot.repositories.pending_executions.list_by_run(run_id=run_id)[-1]


def _writes(bot: VaaniFlowTelegramBot) -> tuple[int, int, int]:
    repos = bot.repositories
    return (
        len(repos.orders.list_all()),
        len(repos.invoices.list_all()),
        len(repos.dispatches.list_all()),
    )


# --------------------------------------------------------------------------- #
# Dynamic approval card
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "customer", "quantity", "tools", "notification"),
    [
        (
            CANONICAL,
            "Sharma Builders",
            "200",
            ["create_order", "create_invoice_draft", "dispatch_order"],
            True,
        ),
        (
            SHARMA_150,
            "Sharma Builders",
            "150",
            ["create_order", "create_invoice_draft", "dispatch_order"],
            False,
        ),
        (KUMAR, "Kumar Constructions", "10", ["create_order", "dispatch_order"], False),
        (KUMAR_15, "Kumar Constructions", "15", ["create_order", "dispatch_order"], False),
    ],
)
def test_approval_card_is_built_from_the_runs_own_state(
    text: str, customer: str, quantity: str, tools: list[str], notification: bool
) -> None:
    bot, client = _bot()
    _send(bot, _msg(text))
    card = _last(client)
    pending = _pending(bot)
    plan = pending.plan

    assert [c.tool_name for c in plan.tool_calls] == tools
    for n, tool in enumerate(tools, start=1):
        assert f"{n}. <code>{tool}</code>" in card
    for absent in {"create_order", "create_invoice_draft", "dispatch_order"} - set(tools):
        assert f"<code>{absent}</code>" not in card
    assert f"Customer: {customer}" in card
    assert f"— {quantity} bag" in card
    assert ("SEND_NOTIFICATION" in card) is notification
    checks = pending.validation_result.checks
    assert f"{len(checks)}/{len(checks)} checks passed" in card
    for check in checks:
        assert check.check_type in card
    # Money comes from the plan's own arguments / tax calculation.
    order = next(c for c in plan.tool_calls if c.tool_name == "create_order").arguments
    line_total = Decimal(str(order["items"][0]["line_total"]))
    assert telegram_views.money(line_total) in card
    if text in (KUMAR, KUMAR_15):
        assert "Sharma Builders" not in card and "Ultratech" not in card.split("Instruction")[0]
    assert _tags(card) <= ALLOWED_TAGS


def test_different_quantities_give_different_totals_and_tax() -> None:
    totals = []
    for text in (CANONICAL, SHARMA_150):
        bot, client = _bot()
        _send(bot, _msg(text))
        invoice = next(
            c.arguments
            for c in _pending(bot).plan.tool_calls
            if c.tool_name == "create_invoice_draft"
        )
        assert telegram_views.money(Decimal(str(invoice["total"]))) in _last(client)
        assert telegram_views.money(Decimal(str(invoice["tax_total"]))) in _last(client)
        totals.append(invoice["total"])
    assert totals[0] != totals[1]


def test_validation_failure_and_clarification_cards_show_the_real_reason() -> None:
    bot, client = _bot()
    _send(
        bot,
        _msg(
            "Sharma Builders ko 2000 bag Ultratech cement dispatch karo. Rate wahi lagana jo parso bataya tha."
        ),
    )
    confirmation = _last(client)
    assert "Please confirm — nothing has been executed" in confirmation
    assert "2000 bag is unusually large" in confirmation

    _send(bot, _msg("Kumar Constructions ko ACC cement ₹400 per bag dispatch karo."))
    clarification = _last(client)
    assert "Clarification needed — nothing has been executed" in clarification
    assert "without a quantity" in clarification
    assert _writes(bot) == (0, 0, 0)


# --------------------------------------------------------------------------- #
# Truthful receipts
# --------------------------------------------------------------------------- #


def _approved(text: str, faults: dict[str, Any] | None = None) -> tuple[WorkflowResult, str]:
    orchestrator = VoiceWorkflowOrchestrator(repositories=SyntheticRepositories(), clock=lambda: T)
    asked = orchestrator.process_text(text=text, now=T)
    assert asked.approval is not None
    result = orchestrator.approve(
        run_id=asked.run.run_id,
        approval_id=asked.approval.approval_id,
        actor=OWNER,
        simulated_faults=faults,
        now=T,
    )
    return result, telegram_views.render_receipt(result, approver=OWNER)


def _assert_marks_match(result: WorkflowResult, receipt: str) -> None:
    counts = {status: 0 for status in StepStatus}
    for step in result.step_outcomes:
        counts[step.status] += 1
    assert receipt.count("<b>VERIFIED</b>") == counts[StepStatus.VERIFIED]
    assert receipt.count("<b>FAILED</b>") == counts[StepStatus.FAILED]
    assert receipt.count("<b>UNKNOWN</b>") == counts[StepStatus.UNKNOWN]
    assert receipt.count("<b>NOT ATTEMPTED</b>") == counts[StepStatus.NOT_ATTEMPTED]


def test_receipt_all_steps_verified() -> None:
    result, receipt = _approved(KUMAR)
    assert result.run.status is VoiceRunStatus.COMPLETED
    assert "Execution complete — every step verified" in receipt
    _assert_marks_match(result, receipt)
    assert "Handoff" not in receipt


def test_receipt_partial_failure_is_explicit() -> None:
    result, receipt = _approved(CANONICAL, {"simulate_dispatch_failure": True})
    assert result.run.status is VoiceRunStatus.PARTIALLY_COMPLETED
    assert "Execution partially completed" in receipt
    assert "Dispatch — <b>FAILED</b>" in receipt
    _assert_marks_match(result, receipt)
    assert "complete — every step verified" not in receipt


def test_receipt_failed_invoice_and_skipped_dispatch_are_never_verified() -> None:
    result, receipt = _approved(CANONICAL, {"simulate_invoice_failure": True})
    statuses = [s.status for s in result.step_outcomes]
    assert statuses == [StepStatus.VERIFIED, StepStatus.FAILED, StepStatus.NOT_ATTEMPTED]
    _assert_marks_match(result, receipt)
    assert "Invoice draft — <b>FAILED</b>" in receipt
    assert "Dispatch — <b>NOT ATTEMPTED</b>" in receipt


def test_receipt_unknown_outcome_is_never_success() -> None:
    result, receipt = _approved(KUMAR, {"simulate_timeout": {"create_order": "before_commit"}})
    assert any(s.status is StepStatus.UNKNOWN for s in result.step_outcomes)
    assert "Execution outcome unknown" in receipt
    assert "No automatic retry was performed. Operator verification required." in receipt
    _assert_marks_match(result, receipt)


def test_receipt_unsupported_notification_is_a_handoff_not_a_sent_message() -> None:
    result, receipt = _approved(CANONICAL)
    assert result.run.status is VoiceRunStatus.HANDOFF
    assert "Execution completed with handoff" in receipt
    assert "SEND_NOTIFICATION: not supported in this prototype — not performed" in receipt
    assert "sent" not in receipt.lower().replace("not supported", "")
    _assert_marks_match(result, receipt)


def test_receipt_for_a_verification_failure_shows_the_step_status() -> None:
    result, _ = _approved(KUMAR)
    failed_verification = StepOutcome(
        tool_name="dispatch_order",
        status=StepStatus.UNKNOWN,
        execution_status="SUCCEEDED",
        verification_status="FAILED",
        message="Read-back did not match the expected dispatch.",
    )
    result.step_outcomes = [result.step_outcomes[0], failed_verification]
    receipt = telegram_views.render_receipt(result, approver=OWNER)
    assert "Execution outcome unknown" in receipt
    assert receipt.count("<b>VERIFIED</b>") == 1
    assert "Read-back did not match" in receipt


def test_expired_approval_is_reported_not_shown_as_executed() -> None:
    bot, client = _bot()
    _send(bot, _msg(KUMAR))
    for inventory in bot.repositories.inventory.list_all():
        inventory.reserved_quantity += 1
    _send(bot, _click(_button(client, "approve")))
    assert client.answered_callbacks[-1]["show_alert"] is True
    assert client.edited_messages == [] and _writes(bot) == (0, 0, 0)
    approval = bot.repositories.approvals.get_by_id(approval_id=_pending(bot).approval_id)
    assert approval is not None and approval.status is ApprovalStatus.EXPIRED


# --------------------------------------------------------------------------- #
# Voice
# --------------------------------------------------------------------------- #


def _speech_wav(seconds: float = 2.0) -> bytes:
    sr = 16000
    t = np.arange(int(sr * seconds)) / sr
    rng = np.random.default_rng(0)
    signal = 0.3 * np.sin(2 * np.pi * 220 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))
    signal += 0.003 * rng.standard_normal(t.size)
    buffer = io.BytesIO()
    sf.write(buffer, signal.astype("float32"), sr, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def _silent_wav() -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(32000, dtype="float32"), 16000, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


class _FailingASR:
    def transcribe(self, *, request: ASRInput, audio: Any) -> Transcript:
        raise ASRProviderUnavailableError("network down")


class _BlankASR:
    def transcribe(self, *, request: ASRInput, audio: Any) -> Transcript:
        return Transcript(
            transcript_id=uuid4(), provider="stub", text="   ", created_at=datetime.now(UTC)
        )


def _voice_bot(
    tmp_path: Path, asr: Any, wav: bytes, monkeypatch: pytest.MonkeyPatch
) -> tuple[VaaniFlowTelegramBot, MockTelegramClient]:
    intake = VoiceIntakeService(
        artifact_storage=LocalArtifactStorage(tmp_path),
        audio_preprocessor=LocalAudioPreprocessor(),
        asr_provider=asr,
    )
    # External boundary: FFmpeg. The bytes given are what FFmpeg would produce.
    monkeypatch.setattr(telegram_bot, "convert_to_pcm16_wav", lambda raw, executable=None: wav)
    return _bot(voice_intake=intake)


def _voice_update() -> dict[str, Any]:
    return _msg("", voice={"file_id": "v1", "duration": 3}, caption=CANONICAL)


def test_voice_transcript_enters_the_same_pipeline_and_is_not_the_demo_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot, client = _voice_bot(
        tmp_path, MockASR(text=KUMAR, provider="mock-asr"), _speech_wav(), monkeypatch
    )
    _send(bot, _voice_update())

    texts = [m["text"] for m in client.sent_messages]
    assert any("Transcribed by <code>mock-asr</code>" in t for t in texts)
    card = _last(client)
    assert "Approval required" in card and "Kumar Constructions" in card
    assert "Sharma" not in card  # neither the caption nor the canonical text was used
    run_id = bot.active_runs[OWNER.principal_id]
    run = bot.repositories.runs.get_by_id(run_id=run_id)
    assert run is not None and run.owner_id == OWNER.principal_id
    understood = bot.repositories.understand_results.list_by_run(run_id=run_id)[-1]
    assert understood.transcript.provider == "mock-asr" and understood.transcript.text == KUMAR
    assert any(p.name for p in (tmp_path / "original").iterdir())  # original kept (write-once)


@pytest.mark.parametrize(
    ("asr", "wav_factory", "code"),
    [
        (_FailingASR(), _speech_wav, "ASR_UNAVAILABLE"),
        (_BlankASR(), _speech_wav, "EMPTY_TRANSCRIPT"),
        (MockASR(text=KUMAR), lambda: b"not a wav file at all", "INVALID_AUDIO"),
    ],
)
def test_voice_failures_create_nothing_and_say_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asr: Any, wav_factory: Any, code: str
) -> None:
    bot, client = _voice_bot(tmp_path, asr, wav_factory(), monkeypatch)
    _send(bot, _voice_update())
    assert f"not processed ({code})" in _last(client)
    assert bot.repositories.runs.list_all() == []


def test_unusable_audio_is_blocked_by_input_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot, client = _voice_bot(tmp_path, MockASR(text=KUMAR), _silent_wav(), monkeypatch)
    _send(bot, _voice_update())
    assert "Blocked — nothing was executed" in _last(client)
    run = bot.repositories.runs.list_all()[0]
    assert run.status is VoiceRunStatus.BLOCKED and _writes(bot) == (0, 0, 0)


def test_voice_conversion_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(raw: bytes, executable: str | None = None) -> bytes:
        raise AudioConversionError("CONVERSION_FAILED", "The audio could not be decoded: bad")

    bot, client = _voice_bot(tmp_path, MockASR(text=KUMAR), b"", monkeypatch)
    monkeypatch.setattr(telegram_bot, "convert_to_pcm16_wav", broken)
    _send(bot, _voice_update())
    assert "not processed (CONVERSION_FAILED)" in _last(client)
    assert bot.repositories.runs.list_all() == []


def test_blocking_voice_work_runs_off_the_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot, _ = _voice_bot(tmp_path, MockASR(text=KUMAR), _speech_wav(), monkeypatch)
    offloaded: list[str] = []
    real = asyncio.to_thread

    async def spy(func: Any, *args: Any, **kwargs: Any) -> Any:
        offloaded.append(getattr(func, "__name__", repr(func)))
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(telegram_bot.asyncio, "to_thread", spy)
    _send(bot, _voice_update())
    _send(bot, _msg("/benchmark"))
    assert "<lambda>" in offloaded and "transcribe_wav" in offloaded and "run_all" in offloaded


def test_voice_intake_service_raises_typed_errors(tmp_path: Path) -> None:
    service = VoiceIntakeService(
        artifact_storage=LocalArtifactStorage(tmp_path),
        audio_preprocessor=LocalAudioPreprocessor(),
        asr_provider=_FailingASR(),
    )
    with pytest.raises(VoiceIntakeError) as raised:
        service.transcribe_wav(_speech_wav(), now=T)
    assert raised.value.code == "ASR_UNAVAILABLE" and "network" not in raised.value.message


# --------------------------------------------------------------------------- #
# FFmpeg
# --------------------------------------------------------------------------- #


def _script(tmp_path: Path, body: str) -> str:
    path = tmp_path / "fake-ffmpeg"
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_ffmpeg_missing_failure_timeout_and_empty_input(tmp_path: Path) -> None:
    with pytest.raises(AudioConversionError) as missing:
        ffmpeg.resolve_ffmpeg({"VAANIFLOW_FFMPEG": str(tmp_path / "nope")})
    assert missing.value.code == "FFMPEG_NOT_FOUND"
    with pytest.raises(AudioConversionError) as not_started:
        convert_to_pcm16_wav(b"x", executable=str(tmp_path / "nope"))
    assert not_started.value.code == "FFMPEG_NOT_FOUND"

    failing = _script(tmp_path, "echo 'Invalid data found when processing input' >&2; exit 1")
    with pytest.raises(AudioConversionError) as failed:
        convert_to_pcm16_wav(b"garbage", executable=failing)
    assert failed.value.code == "CONVERSION_FAILED" and "Invalid data" in failed.value.message

    (tmp_path / "fake-ffmpeg").unlink()
    slow = _script(tmp_path, "sleep 5")
    with pytest.raises(AudioConversionError) as timed_out:
        convert_to_pcm16_wav(b"x", executable=slow, timeout=0.3)
    assert timed_out.value.code == "CONVERSION_TIMEOUT"

    with pytest.raises(AudioConversionError) as empty:
        convert_to_pcm16_wav(b"", executable=slow)
    assert empty.value.code == "EMPTY_INPUT"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_real_ffmpeg_converts_to_16k_mono_pcm16_and_rejects_malformed_input() -> None:
    sr = 44100
    stereo = np.stack([np.sin(2 * np.pi * 300 * np.arange(sr) / sr)] * 2, axis=1) * 0.2
    source = io.BytesIO()
    sf.write(source, stereo.astype("float32"), sr, format="WAV", subtype="PCM_16")
    wav = convert_to_pcm16_wav(source.getvalue())
    info = sf.info(io.BytesIO(wav))
    assert (info.samplerate, info.channels, info.subtype) == (16000, 1, "PCM_16")
    with pytest.raises(AudioConversionError) as malformed:
        convert_to_pcm16_wav(b"OggS" + b"\x00" * 200)
    assert malformed.value.code in {"CONVERSION_FAILED", "EMPTY_OUTPUT"}


# --------------------------------------------------------------------------- #
# Clarification merging
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("original", "reply", "expected_customer", "expected_product", "expected_quantity"),
    [
        (
            "10 bags ACC cement ₹400 per bag dispatch karo.",
            "Kumar Constructions",
            "Kumar Constructions",
            "ACC cement",
            "10",
        ),
        (
            "Kumar Constructions ko ACC cement ₹400 per bag dispatch karo.",
            "10 bag",
            "Kumar Constructions",
            "ACC cement",
            "10",
        ),
        (
            "Kumar Constructions ko 10 bags ACC ya UltraTech cement ₹400 per bag dispatch karo.",
            "ACC cement",
            "Kumar Constructions",
            "ACC cement",
            "10",
        ),
    ],
)
def test_clarification_reply_fills_only_the_asked_slot(
    original: str, reply: str, expected_customer: str, expected_product: str, expected_quantity: str
) -> None:
    bot, client = _bot()
    _send(bot, _msg(original))
    run_id = bot.active_runs[OWNER.principal_id]
    run = bot.repositories.runs.get_by_id(run_id=run_id)
    assert run is not None and run.status is VoiceRunStatus.CLARIFICATION_REQUIRED

    _send(bot, _msg(reply))
    assert bot.active_runs[OWNER.principal_id] == run_id  # same run, not a new one
    state = bot.repositories.understand_results.list_by_run(run_id=run_id)[-1].semantic_state
    assert state.customer is not None and state.customer.surface_text == expected_customer
    assert state.items[0].product is not None
    assert state.items[0].product.surface_text == expected_product
    assert state.items[0].quantity is not None
    assert str(state.items[0].quantity.value) == expected_quantity
    assert [a.action_type.value for a in state.requested_actions] == ["DISPATCH"]
    # Revalidated through ACT: approval is required, nothing executed.
    assert "Approval required" in _last(client)
    assert _writes(bot) == (0, 0, 0)


def test_clarification_preserves_facts_and_resolves_a_context_ambiguity() -> None:
    bot, client = _bot()
    _send(
        bot,
        _msg(
            "Sharma ko 200 bag Ultratech cement dispatch karo. Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST."
        ),
    )
    run_id = bot.active_runs[OWNER.principal_id]
    _send(bot, _msg("Sharma Builders"))
    state = bot.repositories.understand_results.list_by_run(run_id=run_id)[-1].semantic_state
    assert state.customer is not None and state.customer.surface_text == "Sharma Builders"
    assert str(state.items[0].quantity.value) == "200"  # type: ignore[union-attr]
    assert state.pricing and state.pricing[0].amount == Decimal(420)
    assert "Approval required" in _last(client) and "Customer: Sharma Builders" in _last(client)
    assert _writes(bot) == (0, 0, 0)


@pytest.mark.parametrize(
    "reply",
    ["Sharma Builders 10 bag", "haan", "10 bag kal"],
)
def test_clarification_reply_that_changes_other_facts_or_answers_nothing_is_refused(
    reply: str,
) -> None:
    bot, client = _bot()
    _send(bot, _msg("Kumar Constructions ko ACC cement ₹400 per bag dispatch karo."))
    run_id = bot.active_runs[OWNER.principal_id]
    before = len(bot.repositories.understand_results.list_by_run(run_id=run_id))
    _send(bot, _msg(reply))
    assert "Nothing was changed" in _last(client)
    assert len(bot.repositories.understand_results.list_by_run(run_id=run_id)) == before
    run = bot.repositories.runs.get_by_id(run_id=run_id)
    assert run is not None and run.status is VoiceRunStatus.CLARIFICATION_REQUIRED


def test_http_clarify_uses_the_same_merge() -> None:
    container = reset_container(clock=lambda: T, identity_provider=provider())
    client = TestClient(app)
    run_id = client.post("/runs", headers=auth()).json()["run_id"]
    client.post(
        f"/runs/{run_id}/process",
        json={"text": "Kumar Constructions ko ACC cement ₹400 per bag dispatch karo."},
        headers=auth(),
    )
    merged = client.post(
        f"/runs/{run_id}/clarify", json={"clarification": "10 bag"}, headers=auth()
    )
    assert merged.status_code == 200 and merged.json()["status"] == "APPROVAL_REQUIRED"
    assert merged.json()["approval_id"] is not None
    assert len(container.repositories.orders.list_all()) == 0


# --------------------------------------------------------------------------- #
# Shared application state
# --------------------------------------------------------------------------- #


def test_telegram_and_http_api_share_one_application_state() -> None:
    container = reset_container(clock=lambda: T, identity_provider=provider())
    bot, client = _bot(repositories=None, container=container)
    api = TestClient(app)

    _send(bot, _msg(KUMAR))
    run_id = bot.active_runs[OWNER.principal_id]
    audit = api.get(f"/runs/{run_id}/audit", headers=auth(AUDITOR))
    assert audit.status_code == 200
    assert audit.json()["plans"][0]["approval"]["status"] == "REQUESTED"

    _send(bot, _click(_button(client, "approve")))
    after = api.get(f"/runs/{run_id}/audit", headers=auth(AUDITOR)).json()
    approval = after["plans"][0]["approval"]
    assert approval["status"] == "APPROVED"
    assert approval["approved_actor"]["authentication_method"] == "telegram-allowlist"
    assert [v["status"] for v in after["verifications"]] == ["VERIFIED", "VERIFIED"]
    assert api.get(f"/runs/{run_id}", headers=auth(AUDITOR)).json()["status"] == "COMPLETED"

    # And the other way round: a run created over HTTP is in the bot's state.
    api_run = api.post("/runs", headers=auth()).json()["run_id"]
    assert bot.repositories.runs.get_by_id(run_id=UUID(api_run)) is not None
    _send(bot, _msg("/status"))
    assert "Runs: <b>2</b>" in _last(client)


# --------------------------------------------------------------------------- #
# HTML injection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "hostile",
    [
        "<Admin>",
        "<b>Approved</b>",
        "<script>alert(1)</script>",
        '& < > "quoted"',
        "</i></b><a href='x'>click</a>",
    ],
)
def test_user_text_cannot_break_card_formatting(hostile: str) -> None:
    bot, client = _bot()
    _send(
        bot,
        _msg(f"{hostile} Kumar Constructions ko ACC cement ₹400 per bag dispatch karo {hostile}"),
    )
    _send(bot, _msg(hostile))
    for message in client.sent_messages:
        assert _tags(message["text"]) <= ALLOWED_TAGS, message["text"]
        assert "<script" not in message["text"] and "<Admin>" not in message["text"]
    assert any("&lt;" in m["text"] for m in client.sent_messages)


# --------------------------------------------------------------------------- #
# Benchmark and status
# --------------------------------------------------------------------------- #


class _FakeRunner:
    def run_all(self) -> SuiteEvaluationResult:
        def result(sid: ScenarioId, passed: bool) -> ScenarioEvaluationResult:
            return ScenarioEvaluationResult(
                scenario_id=sid,
                passed=passed,
                run_id=uuid4(),
                actual_decision="EXECUTE",
                actual_status="COMPLETED" if passed else "FAILED",
                forbidden_actions_avoided=passed,
                details="ok" if passed else "Failed: dispatched despite <shortage>",
            )

        results = [
            result(ScenarioId.SCENARIO_A, True),
            result(ScenarioId.SCENARIO_B, True),
            result(ScenarioId.SCENARIO_C, False),
        ]
        return SuiteEvaluationResult(
            total_scenarios=3,
            passed_scenarios=2,
            failed_scenarios=1,
            safety_violations=1,
            false_execution_rate=1 / 3,
            evaluation_timestamp=T,
            results=results,
        )


def test_benchmark_card_reflects_whatever_the_evaluation_returns() -> None:
    bot, client = _bot(evaluation_runner=_FakeRunner())
    _send(bot, _msg("/benchmark"))
    card = _last(client)
    assert "2/3 passed</b>, 1 failed" in card
    assert "Safety violations: <b>1</b>" in card and "33.3%" in card
    assert "✗ <code>scenario_c_ambiguous_customer</code>" in card
    assert "dispatched despite &lt;shortage&gt;" in card
    assert "10/10" not in card and "16/16" not in card


def test_status_reflects_the_repositories() -> None:
    bot, client = _bot()
    _send(bot, _msg("/status"))
    assert "Runs: <b>0</b>" in _last(client)
    _send(bot, _msg(KUMAR))
    _send(bot, _click(_button(client, "approve")))
    _send(bot, _msg("/status"))
    status = _last(client)
    assert "Runs: <b>1</b>" in status and "Approvals approved: <b>1</b>" in status
    assert "Orders / invoices / dispatches: <b>1 / 0 / 1</b>" in status
    assert "Customers / products / quotes: <b>4 / 4 /" in status
    assert "WhatsApp / notifications: <b>not supported" in status


def test_clarification_reply_contradicting_a_known_fact_is_refused() -> None:
    """The compiler recognises the customer here, so this exercises the conflict check."""
    bot, client = _bot()
    _send(bot, _msg("Kumar Constructions ko ACC cement ₹400 per bag dispatch karo."))
    run_id = bot.active_runs[OWNER.principal_id]
    _send(bot, _msg("Sharma Builders ko 10 bag"))
    assert "changes customer, which was not asked about" in _last(client)
    state = bot.repositories.understand_results.list_by_run(run_id=run_id)[-1].semantic_state
    assert state.customer is not None and state.customer.surface_text == "Kumar Constructions"
    assert state.items[0].quantity is None


def test_voice_wiring_goes_through_the_gnani_adapter_not_the_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ast

    from vaaniflow.providers.gnani import GnaniASRProvider

    assert telegram_bot.voice_intake_from_env({}) is None  # no key → voice refused
    built: list[bool] = []

    def factory() -> MockASR:
        built.append(True)
        return MockASR(text=KUMAR)

    monkeypatch.setattr(GnaniASRProvider, "from_environment", staticmethod(factory))
    intake = telegram_bot.voice_intake_from_env(
        {"GNANI_API_KEY": "test", "VAANIFLOW_ARTIFACT_DIR": str(tmp_path)}
    )
    assert intake is not None and built == [True]
    # The presentation layer never imports the Gnani SDK itself.
    presentation = Path(telegram_bot.__file__).parent
    for source in presentation.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.ImportFrom | ast.Import):
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                names += [alias.name for alias in node.names]
                assert not any(n.split(".")[0] == "gnani" for n in names), source.name
