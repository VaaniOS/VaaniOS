from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.principal import Principal, Role
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.evaluation.runner import EvaluationRunner
from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories
from vaaniflow.presentation.telegram_bot import TelegramClient, VaaniFlowTelegramBot
from vaaniflow.presentation.telegram_security import TelegramIdentityProvider, decode_id

# Synthetic demo identity: Telegram user 42 is allowlisted as the OWNER "Ramesh".
RAMESH = Principal(
    principal_id=UUID("00000000-0000-4000-8000-00000000d042"),
    display_name="Ramesh (demo owner)",
    roles=[Role.OWNER, Role.REQUESTER],
    authentication_method="telegram-allowlist",
)


class MockTelegramClient(TelegramClient):
    """In-memory mock Telegram client recording sent messages and callbacks."""

    def __init__(self) -> None:
        super().__init__(token="mock_token_123456:ABC-DEF")
        self.sent_messages: list[dict[str, Any]] = []
        self.edited_messages: list[dict[str, Any]] = []
        self.answered_callbacks: list[dict[str, Any]] = []
        self.downloaded_files: list[str] = []

    async def get_me(self) -> dict[str, Any]:
        return {
            "id": 123456789,
            "is_bot": True,
            "first_name": "VaaniFlowBot",
            "username": "vaaniflow_bot",
        }

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "HTML",
    ) -> dict[str, Any]:
        record = {
            "message_id": len(self.sent_messages) + 1,
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.sent_messages.append(record)
        return record

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "HTML",
    ) -> dict[str, Any]:
        record = {
            "message_id": message_id,
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.edited_messages.append(record)
        return record

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> bool:
        self.answered_callbacks.append(
            {
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert,
            }
        )
        return True

    async def get_file(self, file_id: str) -> dict[str, Any]:
        return {"file_id": file_id, "file_path": f"voice/{file_id}.oga"}

    async def download_file(self, file_path: str) -> bytes:
        self.downloaded_files.append(file_path)
        # 44-byte dummy WAV header
        return b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00@\x1f\x00\x00\x80>\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"


@pytest.fixture
def mock_client() -> MockTelegramClient:
    return MockTelegramClient()


@pytest.fixture
def bot(mock_client: MockTelegramClient) -> VaaniFlowTelegramBot:
    repos = SyntheticRepositories()
    return VaaniFlowTelegramBot(
        token="test_token",
        repositories=repos,
        client=mock_client,
        identity=TelegramIdentityProvider({42: RAMESH}),
    )


def _update(text: str, update_id: int = 1) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 100 + update_id,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "first_name": "Ramesh", "username": "ramesh_yard"},
            "text": text,
        },
    }


def _click(data: str, message_id: int = 7) -> dict[str, Any]:
    return {
        "update_id": 99,
        "callback_query": {
            "id": "query_1",
            "from": {"id": 42, "first_name": "Ramesh", "username": "ramesh_yard"},
            "message": {"message_id": message_id, "chat": {"id": 42, "type": "private"}},
            "data": data,
        },
    }


def _button(card: dict[str, Any], verb: str) -> str:
    for row in card["reply_markup"]["inline_keyboard"]:
        for button in row:
            if button["callback_data"].startswith(f"{verb}:"):
                return str(button["callback_data"])
    raise AssertionError(f"no {verb} button")


@pytest.mark.asyncio
async def test_telegram_start_command(
    bot: VaaniFlowTelegramBot, mock_client: MockTelegramClient
) -> None:
    await bot.handle_update(_update("/start"))
    msg = mock_client.sent_messages[-1]
    assert msg["chat_id"] == 42
    assert "Welcome to VaaniFlow, Ramesh (demo owner)!" in msg["text"]
    assert "Voice notes: not configured" in msg["text"]  # no ASR configured in this bot
    assert len(msg["reply_markup"]["inline_keyboard"]) >= 2


@pytest.mark.asyncio
async def test_telegram_demo_card_and_receipt_are_computed_from_backend_state(
    bot: VaaniFlowTelegramBot, mock_client: MockTelegramClient
) -> None:
    await bot.handle_update(_update("/demo"))
    card = mock_client.sent_messages[-1]
    run_id = bot.active_runs[RAMESH.principal_id]
    pending = bot.repositories.pending_executions.list_by_run(run_id=run_id)[-1]
    plan = pending.plan
    validation = pending.validation_result
    invoice_args = next(
        c.arguments for c in plan.tool_calls if c.tool_name == "create_invoice_draft"
    )

    text = card["text"]
    assert "Approval required — nothing has been executed" in text
    assert "Sharma Builders" in text  # resolved from the customer records for this run
    assert "₹1,07,520.00" in text and Decimal(str(invoice_args["total"])) == Decimal("107520.00")
    passed = sum(1 for c in validation.checks if c.status.value == "PASSED")
    assert f"{passed}/{len(validation.checks)} checks passed" in text
    for n, call in enumerate(plan.tool_calls, start=1):
        assert f"{n}. <code>{call.tool_name}</code>" in text
    assert "SEND_NOTIFICATION: not supported in this prototype" in text
    approve = _button(card, "approve")
    assert len(approve.encode()) <= 64
    _, run_part, approval_part = approve.split(":")
    assert decode_id(run_part) == run_id and decode_id(approval_part) == pending.approval_id

    await bot.handle_update(_click(approve, message_id=card["message_id"]))
    assert mock_client.answered_callbacks[-1]["text"] == "Approval recorded."
    receipt = mock_client.edited_messages[-1]["text"]
    # The canonical run ends HANDOFF: three verified writes, WhatsApp not performed.
    run = bot.repositories.runs.get_by_id(run_id=run_id)
    assert run is not None and run.status is VoiceRunStatus.HANDOFF
    assert "Execution completed with handoff" in receipt
    assert receipt.count("<b>VERIFIED</b>") == 3
    assert "SEND_NOTIFICATION: not supported in this prototype — not performed" in receipt
    assert "Ramesh (demo owner) [OWNER, REQUESTER] via telegram-allowlist" in receipt
    approval = bot.repositories.approvals.get_by_id(approval_id=pending.approval_id)
    assert approval is not None and approval.status is ApprovalStatus.APPROVED
    assert approval.approved_actor == RAMESH and approval.actor_authenticated is True
    orders = bot.repositories.orders.list_all()
    assert len(orders) == 1 and orders[0].source_run_id == run_id
    assert run.owner_id == RAMESH.principal_id


@pytest.mark.asyncio
async def test_telegram_rejection_by_allowlisted_owner(
    bot: VaaniFlowTelegramBot, mock_client: MockTelegramClient
) -> None:
    await bot.handle_update(_update(bot.CANONICAL_DEMO_TEXT))
    card = mock_client.sent_messages[-1]
    reject = _button(card, "reject")
    await bot.handle_update(_click(reject, message_id=card["message_id"]))

    assert mock_client.answered_callbacks[-1]["text"] == "Plan rejected."
    assert "Execution plan rejected" in mock_client.edited_messages[-1]["text"]
    assert bot.repositories.orders.list_all() == []
    approval_id = decode_id(reject.split(":")[2])
    assert approval_id is not None
    approval = bot.repositories.approvals.get_by_id(approval_id=approval_id)
    assert approval is not None and approval.status is ApprovalStatus.REJECTED
    assert approval.rejected_by == RAMESH.principal_id and approval.rejected_actor == RAMESH


@pytest.mark.asyncio
async def test_voice_note_without_configured_asr_is_refused_not_substituted(
    bot: VaaniFlowTelegramBot, mock_client: MockTelegramClient
) -> None:
    voice_update = _update("", update_id=6)
    voice_update["message"]["voice"] = {"file_id": "voice_file_abc", "duration": 6}
    voice_update["message"]["caption"] = bot.CANONICAL_DEMO_TEXT
    await bot.handle_update(voice_update)

    assert "Voice notes are not available" in mock_client.sent_messages[-1]["text"]
    assert mock_client.downloaded_files == []
    assert bot.repositories.runs.list_all() == []  # neither caption nor demo text is used


@pytest.mark.asyncio
async def test_benchmark_and_status_are_computed(
    bot: VaaniFlowTelegramBot, mock_client: MockTelegramClient
) -> None:
    await bot.handle_update(_update("/benchmark"))
    suite = EvaluationRunner().run_all()
    bench = mock_client.sent_messages[-1]["text"]
    assert f"{suite.passed_scenarios}/{suite.total_scenarios} passed" in bench
    assert f"Safety violations: <b>{suite.safety_violations}</b>" in bench
    for result in suite.results:
        assert result.scenario_id.value in bench

    await bot.handle_update(_update("/status", update_id=2))
    first = mock_client.sent_messages[-1]["text"]
    assert "Runs: <b>0</b>" in first
    await bot.handle_update(_update(bot.CANONICAL_DEMO_TEXT, update_id=3))
    await bot.handle_update(_update("/status", update_id=4))
    second = mock_client.sent_messages[-1]["text"]
    assert "Runs: <b>1</b>" in second and "Approvals pending: <b>1</b>" in second
    assert "Speech-to-text: <b>not configured</b>" in second
