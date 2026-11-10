from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from vaaniflow.infrastructure.repositories.synthetic_data import SyntheticRepositories
from vaaniflow.presentation.telegram_bot import TelegramClient, VaaniFlowTelegramBot


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
    return VaaniFlowTelegramBot(token="test_token", repositories=repos, client=mock_client)


@pytest.mark.asyncio
async def test_telegram_start_command(
    bot: VaaniFlowTelegramBot, mock_client: MockTelegramClient
) -> None:
    update = {
        "update_id": 1,
        "message": {
            "message_id": 101,
            "chat": {"id": 999},
            "from": {"id": 42, "first_name": "Ramesh", "username": "ramesh_yard"},
            "text": "/start",
        },
    }
    await bot.handle_update(update)

    assert len(mock_client.sent_messages) == 1
    msg = mock_client.sent_messages[0]
    assert msg["chat_id"] == 999
    assert "Welcome to VaaniFlow, Ramesh!" in msg["text"]
    assert msg["reply_markup"] is not None
    assert len(msg["reply_markup"]["inline_keyboard"]) >= 2


@pytest.mark.asyncio
async def test_telegram_demo_and_inline_approval_flow(
    bot: VaaniFlowTelegramBot,
    mock_client: MockTelegramClient,
) -> None:
    # 1. User sends /demo
    update = {
        "update_id": 2,
        "message": {
            "message_id": 102,
            "chat": {"id": 999},
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
    run_id = UUID(parts[1])
    _ = UUID(parts[2])

    # 2. User clicks [Approve Dispatch] inline button
    click_update = {
        "update_id": 3,
        "callback_query": {
            "id": "query_777",
            "from": {"id": 42, "first_name": "Ramesh", "username": "ramesh_yard"},
            "message": {"message_id": approval_card["message_id"], "chat": {"id": 999}},
            "data": callback_data,
        },
    }
    await bot.handle_update(click_update)

    # Verify callback answered
    assert len(mock_client.answered_callbacks) == 1
    assert "Approved" in (mock_client.answered_callbacks[0]["text"] or "")

    # Verify message was updated with verified execution receipt
    assert len(mock_client.edited_messages) == 1
    edited = mock_client.edited_messages[0]
    assert "Order Approved &amp; Executed" in edited["text"]
    assert "@ramesh_yard [OWNER]" in edited["text"]
    assert "create_order" in edited["text"]
    assert "dispatch_order" in edited["text"]
    assert "VERIFIED" in edited["text"]

    # Verify DB state
    orders = bot.repositories.orders.list_all()
    assert len(orders) == 1
    assert orders[0].source_run_id == run_id
    assert str(orders[0].subtotal) == "84000.00"


@pytest.mark.asyncio
async def test_telegram_rejection_flow(
    bot: VaaniFlowTelegramBot,
    mock_client: MockTelegramClient,
) -> None:
    update = {
        "update_id": 4,
        "message": {
            "message_id": 103,
            "chat": {"id": 888},
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
            "message": {"message_id": approval_card["message_id"], "chat": {"id": 888}},
            "data": callback_data,
        },
    }
    await bot.handle_update(click_update)

    assert len(mock_client.edited_messages) == 1
    edited = mock_client.edited_messages[0]
    assert "Execution Plan Rejected" in edited["text"]
    assert "No database writes were committed" in edited["text"]
    assert len(bot.repositories.orders.list_all()) == 0


@pytest.mark.asyncio
async def test_telegram_voice_message_intake(
    bot: VaaniFlowTelegramBot,
    mock_client: MockTelegramClient,
) -> None:
    voice_update = {
        "update_id": 6,
        "message": {
            "message_id": 104,
            "chat": {"id": 777},
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
                "chat": {"id": 777},
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
                "chat": {"id": 777},
                "from": {"id": 42, "first_name": "Ramesh"},
                "text": "/status",
            },
        }
    )
    status_msg = mock_client.sent_messages[-1]
    assert "VaaniFlow System Status" in status_msg["text"]
    assert "All Systems Nominal" in status_msg["text"]
