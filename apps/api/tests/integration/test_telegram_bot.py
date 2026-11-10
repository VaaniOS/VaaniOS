from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.principal import Principal, Role
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


@pytest.mark.asyncio
async def test_telegram_start_command(
    bot: VaaniFlowTelegramBot, mock_client: MockTelegramClient
) -> None:
    update = {
        "update_id": 1,
        "message": {
            "message_id": 101,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "first_name": "Ramesh", "username": "ramesh_yard"},
            "text": "/start",
        },
    }
    await bot.handle_update(update)

    assert len(mock_client.sent_messages) == 1
    msg = mock_client.sent_messages[0]
    assert msg["chat_id"] == 42
    assert "Welcome to VaaniFlow, Ramesh (demo owner)!" in msg["text"]
    assert msg["reply_markup"] is not None
    assert len(msg["reply_markup"]["inline_keyboard"]) >= 2


@pytest.mark.asyncio
async def test_telegram_demo_and_inline_approval_by_allowlisted_owner(
    bot: VaaniFlowTelegramBot,
    mock_client: MockTelegramClient,
) -> None:
    # 1. User sends /demo
    update = {
        "update_id": 2,
        "message": {
            "message_id": 102,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "first_name": "Ramesh", "username": "ramesh_yard"},
            "text": "/demo",
        },
    }
    await bot.handle_update(update)

    # Bot should send: 1. "Simulating incoming voice note..." 2. Approval card
    assert len(mock_client.sent_messages) == 2
    approval_card = mock_client.sent_messages[1]
    assert "VaaniFlow — Approval Required" in approval_card["text"]
    assert "Sharma Builders" in approval_card["text"]
    assert "107,520.00" in approval_card["text"]
    assert "8/8 Deterministic Checks" in approval_card["text"]

    # Extract approve callback data
    markup = approval_card["reply_markup"]
    assert markup is not None
    approve_btn = markup["inline_keyboard"][0][0]
    assert approve_btn["text"].startswith("✅ Approve Dispatch")
    callback_data = approve_btn["callback_data"]
    assert callback_data.startswith("approve:")

    parts = callback_data.split(":")
    run_id = decode_id(parts[1])
    approval_id = decode_id(parts[2])
    assert run_id is not None and approval_id is not None
    assert len(callback_data.encode()) <= 64  # Telegram's callback_data limit

    # 2. User clicks [Approve Dispatch] inline button
    click_update = {
        "update_id": 3,
        "callback_query": {
            "id": "query_777",
            "from": {"id": 42, "first_name": "Ramesh", "username": "ramesh_yard"},
            "message": {
                "message_id": approval_card["message_id"],
                "chat": {"id": 42, "type": "private"},
            },
            "data": callback_data,
        },
    }
    await bot.handle_update(click_update)

    # The allowlisted OWNER approves; the orchestrator records that principal.
    assert len(mock_client.answered_callbacks) == 1
    assert mock_client.answered_callbacks[0]["text"] == "Approval recorded."
    assert len(mock_client.edited_messages) == 1
    edited = mock_client.edited_messages[0]["text"]
    assert "Ramesh (demo owner) [OWNER, REQUESTER] via telegram-allowlist" in edited
    orders = bot.repositories.orders.list_all()
    assert len(orders) == 1 and orders[0].source_run_id == run_id
    approval = bot.repositories.approvals.get_by_id(approval_id=approval_id)
    assert approval is not None and approval.status is ApprovalStatus.APPROVED
    assert approval.approved_by == RAMESH.principal_id and approval.approved_actor == RAMESH
    assert approval.actor_authenticated is True
    run = bot.repositories.runs.get_by_id(run_id=run_id)
    assert run is not None and run.owner_id == RAMESH.principal_id


@pytest.mark.asyncio
async def test_telegram_rejection_by_allowlisted_owner(
    bot: VaaniFlowTelegramBot,
    mock_client: MockTelegramClient,
) -> None:
    update = {
        "update_id": 4,
        "message": {
            "message_id": 103,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "first_name": "Ramesh", "username": "ramesh_yard"},
            "text": bot.CANONICAL_DEMO_TEXT,
        },
    }
    await bot.handle_update(update)

    approval_card = mock_client.sent_messages[0]
    markup = approval_card["reply_markup"]
    assert markup is not None
    reject_btn = markup["inline_keyboard"][1][1]
    assert "Reject" in reject_btn["text"]
    callback_data = reject_btn["callback_data"]

    # Tap reject
    click_update = {
        "update_id": 5,
        "callback_query": {
            "id": "query_888",
            "from": {"id": 42, "first_name": "Ramesh", "username": "ramesh_yard"},
            "message": {
                "message_id": approval_card["message_id"],
                "chat": {"id": 42, "type": "private"},
            },
            "data": callback_data,
        },
    }
    await bot.handle_update(click_update)

    assert mock_client.answered_callbacks[-1]["text"] == "Plan rejected."
    assert "Execution Plan Rejected" in mock_client.edited_messages[-1]["text"]
    assert bot.repositories.orders.list_all() == []
    approval_id = decode_id(callback_data.split(":")[2])
    assert approval_id is not None
    approval = bot.repositories.approvals.get_by_id(approval_id=approval_id)
    assert approval is not None and approval.status is ApprovalStatus.REJECTED
    assert approval.rejected_by == RAMESH.principal_id and approval.rejected_actor == RAMESH


@pytest.mark.asyncio
async def test_telegram_voice_message_intake(
    bot: VaaniFlowTelegramBot,
    mock_client: MockTelegramClient,
) -> None:
    voice_update = {
        "update_id": 6,
        "message": {
            "message_id": 104,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "first_name": "Ramesh", "username": "ramesh_yard"},
            "voice": {
                "file_id": "voice_file_abc",
                "duration": 6,
                "mime_type": "audio/ogg",
            },
            "caption": bot.CANONICAL_DEMO_TEXT,
        },
    }
    await bot.handle_update(voice_update)

    assert "voice/voice_file_abc.oga" in mock_client.downloaded_files
    # Bot sends processing notice then approval card
    assert len(mock_client.sent_messages) == 2
    assert "Received 6s voice note" in mock_client.sent_messages[0]["text"]
    assert "VaaniFlow — Approval Required" in mock_client.sent_messages[1]["text"]


@pytest.mark.asyncio
async def test_telegram_benchmark_and_status_commands(
    bot: VaaniFlowTelegramBot,
    mock_client: MockTelegramClient,
) -> None:
    # Test /benchmark
    await bot.handle_update(
        {
            "update_id": 7,
            "message": {
                "message_id": 105,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42, "first_name": "Ramesh"},
                "text": "/benchmark",
            },
        }
    )
    bench_msg = mock_client.sent_messages[-1]
    assert "Evaluation Benchmark Suite (A–J)" in bench_msg["text"]
    assert "10 / 10" in bench_msg["text"]
    assert "0.0%" in bench_msg["text"]

    # Test /status
    await bot.handle_update(
        {
            "update_id": 8,
            "message": {
                "message_id": 106,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42, "first_name": "Ramesh"},
                "text": "/status",
            },
        }
    )
    status_msg = mock_client.sent_messages[-1]
    assert "VaaniFlow System Status" in status_msg["text"]
    assert "All Systems Nominal" in status_msg["text"]
