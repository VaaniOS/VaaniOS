"""
Phase 2 — Telegram identity, authorization, callback integrity and secret hygiene.

Chain under test: Telegram user id → explicit allowlist → Principal → the same
VaaniFlow authorization (permissions, run ownership, run state) as the HTTP API.
All identities here are synthetic demo identities.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from tests.integration.test_telegram_bot import MockTelegramClient
from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.followup import ConfirmationStatus
from vaaniflow.domain.models.principal import SYNTHETIC_EVALUATION_OWNER, Principal, Role
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.infrastructure.repositories.synthetic_data import (
    SYNTHETIC_BUSINESS_TIME,
    SyntheticRepositories,
)
from vaaniflow.presentation.telegram_bot import (
    TelegramAPIError,
    TelegramClient,
    VaaniFlowTelegramBot,
)
from vaaniflow.presentation.telegram_security import (
    TELEGRAM_AUTHENTICATION_METHOD,
    TelegramIdentityProvider,
    approve_data,
    clarify_data,
    confirm_data,
    decode_id,
    encode_id,
    parse_callback,
    redact,
    reject_data,
)

T = SYNTHETIC_BUSINESS_TIME
KUMAR = "Kumar Constructions ko 10 bags ACC cement ₹400 per bag dispatch karo."
KUMAR_11 = "Kumar Constructions ko 11 bags ACC cement ₹400 per bag dispatch karo."
LARGE = (
    "Sharma Builders ko 2000 bag Ultratech cement dispatch karo. "
    "Rate wahi lagana jo parso bataya tha."
)
AMBIGUOUS = "Sharma Builders ko 200 bags UltraTech ya ACC cement dispatch karo, parso."


def _principal(n: int, name: str, *roles: Role) -> Principal:
    return Principal(
        principal_id=UUID(f"00000000-0000-4000-8000-00000000c{n:03d}"),
        display_name=name,
        roles=list(roles),
        authentication_method=TELEGRAM_AUTHENTICATION_METHOD,
    )


# Telegram user id → principal (synthetic).
ASHA_ID, BILAL_ID, OWNER_ID, AUDITOR_ID, OPERATOR_ID, UNKNOWN_ID = 101, 202, 303, 404, 505, 999
ASHA = _principal(1, "Asha (requester)", Role.REQUESTER)
BILAL = _principal(2, "Bilal (requester)", Role.REQUESTER)
OWNER = _principal(3, "Ramesh (owner)", Role.OWNER)
AUDITOR = _principal(4, "Auditor", Role.AUDITOR)
OPERATOR = _principal(5, "Operator", Role.OPERATOR)
ALLOWLIST = {
    ASHA_ID: ASHA,
    BILAL_ID: BILAL,
    OWNER_ID: OWNER,
    AUDITOR_ID: AUDITOR,
    OPERATOR_ID: OPERATOR,
}
TOKEN = "123456789:AAH-telegram-demo-SECRET-token-value"


def _bot() -> tuple[VaaniFlowTelegramBot, MockTelegramClient]:
    client = MockTelegramClient()
    bot = VaaniFlowTelegramBot(
        token=TOKEN,
        repositories=SyntheticRepositories(),
        client=client,
        identity=TelegramIdentityProvider(ALLOWLIST),
    )
    return bot, client


def _msg(user_id: int, text: str, **sender: Any) -> dict[str, Any]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {
                "id": sender.pop("chat_id", user_id),
                "type": sender.pop("chat_type", "private"),
            },
            "from": {"id": user_id, "first_name": "User", **sender},
            "text": text,
        },
    }


def _cb(user_id: int, data: Any, **sender: Any) -> dict[str, Any]:
    return {
        "update_id": 2,
        "callback_query": {
            "id": f"q-{uuid4()}",
            "data": data,
            "from": {"id": user_id, "first_name": "User", **sender},
            "message": {
                "message_id": 7,
                "chat": {"id": sender.pop("chat_id", user_id), "type": "private"},
            },
        },
    }


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _send(bot: VaaniFlowTelegramBot, update: dict[str, Any]) -> None:
    _run(bot.handle_update(update))


def _writes(bot: VaaniFlowTelegramBot) -> tuple[int, int, int]:
    repos = bot.repositories
    return (
        len(repos.orders.list_all()),
        len(repos.invoices.list_all()),
        len(repos.dispatches.list_all()),
    )


def _last_buttons(client: MockTelegramClient) -> dict[str, str]:
    for message in reversed(client.sent_messages):
        markup = message.get("reply_markup")
        if markup:
            return {
                b["callback_data"].split(":")[0]: b["callback_data"]
                for row in markup["inline_keyboard"]
                for b in row
            }
    raise AssertionError("no buttons were sent")


def _requested(bot: VaaniFlowTelegramBot, user_id: int, text: str = KUMAR) -> tuple[UUID, UUID]:
    """``user_id`` submits ``text``; returns (run_id, approval_id) of the approval card."""
    _send(bot, _msg(user_id, text))
    run_id = bot.active_runs[ALLOWLIST[user_id].principal_id]
    approval = bot.repositories.pending_executions.list_by_run(run_id=run_id)[-1]
    return run_id, approval.approval_id


def _approval(bot: VaaniFlowTelegramBot, approval_id: UUID) -> Any:
    record = bot.repositories.approvals.get_by_id(approval_id=approval_id)
    assert record is not None
    return record


def _answer(client: MockTelegramClient) -> str:
    return client.answered_callbacks[-1]["text"] or ""


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #


def test_allowlisted_owner_authenticates_as_its_principal() -> None:
    bot, client = _bot()
    _send(bot, _msg(OWNER_ID, "/start"))
    assert "Welcome to VaaniFlow, Ramesh (owner)!" in client.sent_messages[-1]["text"]
    assert bot.identity.authenticate(OWNER_ID) == OWNER


def test_allowlisted_non_owner_gets_exactly_its_configured_roles() -> None:
    bot, _client = _bot()
    principal = bot.identity.authenticate(ASHA_ID)
    assert principal is not None and principal.roles == [Role.REQUESTER]
    run_id, _approval_id = _requested(bot, ASHA_ID)
    run = bot.repositories.runs.get_by_id(run_id=run_id)
    assert run is not None and run.owner_id == ASHA.principal_id  # not the Telegram id


def test_unknown_telegram_user_is_denied_and_nothing_is_created() -> None:
    bot, client = _bot()
    for text in ("/start", "/demo", KUMAR, "/benchmark", "/status"):
        _send(bot, _msg(UNKNOWN_ID, text))
        assert "not on this bot's allowlist" in client.sent_messages[-1]["text"]
    assert bot.repositories.runs.list_all() == [] and bot.active_runs == {}


def test_unset_allowlist_denies_everyone() -> None:
    client = MockTelegramClient()
    bot = VaaniFlowTelegramBot(
        token=TOKEN, client=client, identity=TelegramIdentityProvider.from_env({})
    )
    _send(bot, _msg(OWNER_ID, KUMAR))
    assert "not on this bot's allowlist" in client.sent_messages[-1]["text"]
    assert bot.repositories.runs.list_all() == []


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '["303"]',
        (
            '{"@ramesh": {"actor_id": "00000000-0000-4000-8000-000000000001", "name": "x",'
            ' "roles": ["OWNER"]}}'
        ),
        (
            '{"0": {"actor_id": "00000000-0000-4000-8000-000000000001", "name": "x",'
            ' "roles": ["OWNER"]}}'
        ),
        (
            '{"-5": {"actor_id": "00000000-0000-4000-8000-000000000001", "name": "x",'
            ' "roles": ["OWNER"]}}'
        ),
        '{"303": "OWNER"}',
        '{"303": {"actor_id": "not-a-uuid", "name": "x", "roles": ["OWNER"]}}',
        (
            '{"303": {"actor_id": "00000000-0000-4000-8000-000000000001", "name": "x",'
            ' "roles": ["ADMIN"]}}'
        ),
        '{"303": {"actor_id": "00000000-0000-4000-8000-000000000001", "name": "x", "roles": []}}',
        '{"303": {"actor_id": "00000000-0000-4000-8000-000000000001", "roles": ["OWNER"]}}',
    ],
)
def test_malformed_allowlist_fails_closed(raw: str) -> None:
    with pytest.raises(ValueError):
        TelegramIdentityProvider.from_env({"TELEGRAM_PRINCIPALS": raw})


def test_allowlist_from_environment_maps_user_id_to_principal() -> None:
    provider = TelegramIdentityProvider.from_env(
        {
            "TELEGRAM_PRINCIPALS": '{"303": {"actor_id": "00000000-0000-4000-8000-00000000d001",'
            ' "name": "Demo Owner", "roles": ["OWNER"]}}'
        }
    )
    principal = provider.authenticate(303)
    assert principal is not None and principal.roles == [Role.OWNER]
    assert principal.principal_id == UUID("00000000-0000-4000-8000-00000000d001")
    assert principal.authentication_method == "telegram-allowlist"
    # Only the plain integer id authenticates.
    for other in ("303", 303.0, True, None, 304):
        assert provider.authenticate(other) is None


def test_provider_refuses_principals_that_are_not_telegram_allowlisted() -> None:
    bearer = OWNER.model_copy(update={"authentication_method": "bearer-token"})
    with pytest.raises(ValueError):
        TelegramIdentityProvider({OWNER_ID: bearer})
    with pytest.raises(ValueError):
        TelegramIdentityProvider({OWNER_ID: SYNTHETIC_EVALUATION_OWNER})
    with pytest.raises(ValueError):
        TelegramIdentityProvider({"303": OWNER})  # type: ignore[dict-item]


@pytest.mark.parametrize(
    "sender",
    [
        {"username": "ramesh_owner"},
        {"first_name": "Ramesh (owner)"},
        {"first_name": "Ramesh (owner)", "username": "ramesh_owner", "roles": ["OWNER"]},
    ],
)
def test_username_or_display_name_cannot_impersonate_an_allowlisted_id(
    sender: dict[str, Any],
) -> None:
    bot, client = _bot()
    _send(bot, _msg(UNKNOWN_ID, KUMAR, **sender))
    assert "not on this bot's allowlist" in client.sent_messages[-1]["text"]
    assert bot.repositories.runs.list_all() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"chat_type": "group"},
        {"chat_type": "supergroup"},
        {"chat_id": -100123},  # another chat id than the sender
        {"is_bot": True},
    ],
)
def test_only_a_private_chat_with_the_user_itself_is_accepted(overrides: dict[str, Any]) -> None:
    bot, client = _bot()
    _send(bot, _msg(OWNER_ID, KUMAR, **overrides))
    assert client.sent_messages[-1]["text"].startswith("⛔")
    assert bot.repositories.runs.list_all() == []


# --------------------------------------------------------------------------- #
# Ownership
# --------------------------------------------------------------------------- #


def test_user_owns_and_continues_their_own_run() -> None:
    bot, _ = _bot()
    run_id, first = _requested(bot, ASHA_ID)
    run_2, _second = _requested(bot, ASHA_ID, KUMAR_11)
    assert run_2 == run_id  # the follow-up went to Asha's own open run
    assert _approval(bot, first).status is ApprovalStatus.SUPERSEDED


def test_another_user_never_touches_the_first_users_run() -> None:
    bot, _ = _bot()
    run_a, approval_a = _requested(bot, ASHA_ID)
    run_b, _ = _requested(bot, BILAL_ID)
    assert run_b != run_a
    assert _approval(bot, approval_a).status is ApprovalStatus.REQUESTED
    run = bot.repositories.runs.get_by_id(run_id=run_b)
    assert run is not None and run.owner_id == BILAL.principal_id


def test_user_cannot_clarify_another_users_run_or_adopt_an_arbitrary_run() -> None:
    bot, client = _bot()
    run_a, approval_a = _requested(bot, ASHA_ID)
    _send(bot, _cb(BILAL_ID, clarify_data(run_a)))
    assert "FORBIDDEN" in _answer(client)
    assert BILAL.principal_id not in bot.active_runs

    _send(bot, _cb(BILAL_ID, clarify_data(uuid4())))
    assert "RUN_NOT_FOUND" in _answer(client)

    # Bilal's next instruction still goes to a new run of his own.
    _send(bot, _msg(BILAL_ID, KUMAR_11))
    assert bot.active_runs[BILAL.principal_id] != run_a
    assert _approval(bot, approval_a).status is ApprovalStatus.REQUESTED


def test_user_can_clarify_their_own_open_run() -> None:
    bot, client = _bot()
    _send(bot, _msg(ASHA_ID, AMBIGUOUS))
    run_id = bot.active_runs[ASHA.principal_id]
    run = bot.repositories.runs.get_by_id(run_id=run_id)
    assert run is not None and run.status is VoiceRunStatus.CLARIFICATION_REQUIRED
    _send(bot, _cb(ASHA_ID, clarify_data(run_id)))
    assert "Please send your clarification" in client.sent_messages[-1]["text"]
    _send(bot, _msg(ASHA_ID, KUMAR))
    assert bot.active_runs[ASHA.principal_id] == run_id
    run = bot.repositories.runs.get_by_id(run_id=run_id)
    assert run is not None and run.status is VoiceRunStatus.APPROVAL_REQUIRED


def test_completed_run_is_never_reopened() -> None:
    bot, client = _bot()
    run_a, approval_a = _requested(bot, ASHA_ID)
    _send(bot, _cb(OWNER_ID, approve_data(run_a, approval_a)))
    assert _writes(bot) == (1, 0, 1)

    for user in (ASHA_ID, BILAL_ID):
        _send(bot, _cb(user, clarify_data(run_a)))
        assert "RUN_CLOSED" in _answer(client)
    # Asha's next instruction starts a new run instead of reopening the completed one.
    _send(bot, _msg(ASHA_ID, KUMAR_11))
    assert bot.active_runs[ASHA.principal_id] != run_a
    run = bot.repositories.runs.get_by_id(run_id=run_a)
    assert run is not None and run.status is VoiceRunStatus.COMPLETED
    assert _writes(bot) == (1, 0, 1)


def test_escalated_run_is_never_reopened() -> None:
    bot, client = _bot()
    run_a, approval_a = _requested(bot, ASHA_ID)
    bot.orchestrator.escalate(run_id=run_a, reason="Customer called", actor=OPERATOR, now=T)

    for user in (ASHA_ID, BILAL_ID, OPERATOR_ID):
        _send(bot, _cb(user, clarify_data(run_a)))
        assert "RUN_ESCALATED" in _answer(client)
    _send(bot, _cb(OWNER_ID, approve_data(run_a, approval_a)))
    assert "APPROVAL_SUPERSEDED" in _answer(client)
    _send(bot, _msg(ASHA_ID, KUMAR_11))
    assert bot.active_runs[ASHA.principal_id] != run_a
    run = bot.repositories.runs.get_by_id(run_id=run_a)
    assert run is not None and run.status is VoiceRunStatus.HANDOFF
    assert _writes(bot) == (0, 0, 0)


# --------------------------------------------------------------------------- #
# Approval
# --------------------------------------------------------------------------- #


def test_allowlisted_owner_approves_and_is_recorded_with_telegram_provenance() -> None:
    bot, client = _bot()
    run_a, approval_a = _requested(bot, ASHA_ID)
    _send(bot, _cb(OWNER_ID, approve_data(run_a, approval_a)))

    assert _answer(client) == "Approval recorded."
    record = _approval(bot, approval_a)
    assert record.status is ApprovalStatus.APPROVED
    assert record.approved_by == OWNER.principal_id and record.approved_actor == OWNER
    assert record.approved_actor.authentication_method == "telegram-allowlist"
    assert record.actor_authenticated is True and record.requested_by == ASHA.principal_id
    assert "Ramesh (owner) [OWNER] via telegram-allowlist" in client.edited_messages[-1]["text"]
    assert _writes(bot) == (1, 0, 1)


@pytest.mark.parametrize("user", [ASHA_ID, BILAL_ID, AUDITOR_ID, OPERATOR_ID, UNKNOWN_ID])
def test_non_owner_or_unknown_user_cannot_approve_or_reject(user: int) -> None:
    bot, client = _bot()
    run_a, approval_a = _requested(bot, ASHA_ID)
    for data in (approve_data(run_a, approval_a), reject_data(run_a, approval_a)):
        _send(bot, _cb(user, data))
        answer = _answer(client)
        assert "FORBIDDEN" in answer or "not on this bot's allowlist" in answer
    record = _approval(bot, approval_a)
    assert record.status is ApprovalStatus.REQUESTED and record.approved_by is None
    assert record.actor_authenticated is False
    assert client.edited_messages == [] and _writes(bot) == (0, 0, 0)


@pytest.mark.parametrize(
    "suffix",
    [":OWNER", ":actor=00000000-0000-4000-8000-00000000c003", ":roles=OWNER", ":303"],
)
def test_callback_cannot_inject_identity_or_role(suffix: str) -> None:
    bot, client = _bot()
    run_a, approval_a = _requested(bot, ASHA_ID)
    _send(bot, _cb(ASHA_ID, approve_data(run_a, approval_a) + suffix))
    assert _answer(client) == "This button is not valid."
    # Extra fields in the Telegram sender object are not identity either.
    _send(bot, _cb(ASHA_ID, approve_data(run_a, approval_a), roles=["OWNER"], is_owner=True))
    assert "FORBIDDEN" in _answer(client)
    assert _approval(bot, approval_a).status is ApprovalStatus.REQUESTED
    assert _writes(bot) == (0, 0, 0)


def test_stale_approvals_are_refused_against_current_state() -> None:
    bot, client = _bot()
    run_a, first = _requested(bot, ASHA_ID)
    _, second = _requested(bot, ASHA_ID, KUMAR_11)  # supersedes the first
    _send(bot, _cb(OWNER_ID, approve_data(run_a, first)))
    assert "APPROVAL_SUPERSEDED" in _answer(client)

    for inventory in bot.repositories.inventory.list_all():
        inventory.reserved_quantity += 1  # the business snapshot changes before approval
    _send(bot, _cb(OWNER_ID, approve_data(run_a, second)))
    assert _approval(bot, second).status is ApprovalStatus.EXPIRED
    assert client.answered_callbacks[-1]["show_alert"] is True
    assert client.edited_messages == []  # no receipt for an expired approval
    assert _writes(bot) == (0, 0, 0)


def test_repeated_or_post_rejection_clicks_never_execute_twice() -> None:
    bot, client = _bot()
    run_a, approval_a = _requested(bot, ASHA_ID)
    _send(bot, _cb(OWNER_ID, approve_data(run_a, approval_a)))
    _send(bot, _cb(OWNER_ID, approve_data(run_a, approval_a)))
    assert "APPROVAL_NOT_PENDING" in _answer(client)
    assert _writes(bot) == (1, 0, 1)

    run_b, approval_b = _requested(bot, BILAL_ID, KUMAR_11)
    _send(bot, _cb(OWNER_ID, reject_data(run_b, approval_b)))
    _send(bot, _cb(OWNER_ID, approve_data(run_b, approval_b)))
    assert "APPROVAL_NOT_PENDING" in _answer(client)
    assert _writes(bot) == (1, 0, 1)


def test_wrong_approval_run_pair_is_rejected() -> None:
    bot, client = _bot()
    run_a, approval_a = _requested(bot, ASHA_ID)
    run_b, _ = _requested(bot, BILAL_ID, KUMAR_11)
    _send(bot, _cb(OWNER_ID, approve_data(run_b, approval_a)))
    assert "APPROVAL_RUN_MISMATCH" in _answer(client)
    assert _approval(bot, approval_a).status is ApprovalStatus.REQUESTED
    assert _writes(bot) == (0, 0, 0) and run_a != run_b


def test_callbacks_after_a_restart_refer_to_nothing_and_change_nothing() -> None:
    old_bot, _ = _bot()
    run_a, approval_a = _requested(old_bot, ASHA_ID)
    new_bot, client = _bot()  # in-memory state is gone after a restart
    _send(new_bot, _cb(OWNER_ID, approve_data(run_a, approval_a)))
    assert "NOT_FOUND" in _answer(client)
    assert _writes(new_bot) == (0, 0, 0)


# --------------------------------------------------------------------------- #
# Rejection
# --------------------------------------------------------------------------- #


def test_owner_rejection_is_recorded_and_executes_nothing() -> None:
    bot, client = _bot()
    run_a, approval_a = _requested(bot, ASHA_ID)
    _send(bot, _cb(OWNER_ID, reject_data(run_a, approval_a)))
    record = _approval(bot, approval_a)
    assert record.status is ApprovalStatus.REJECTED
    assert record.rejected_by == OWNER.principal_id and record.rejected_actor == OWNER
    assert "Rejected by Ramesh (owner)" in client.edited_messages[-1]["text"]
    assert _writes(bot) == (0, 0, 0)
    assert bot.repositories.tool_executions.list_by_run(run_id=run_a) == []


# --------------------------------------------------------------------------- #
# Confirmation
# --------------------------------------------------------------------------- #


def _confirmation_run(bot: VaaniFlowTelegramBot, client: MockTelegramClient) -> UUID:
    _send(bot, _msg(ASHA_ID, LARGE))
    run_id = bot.active_runs[ASHA.principal_id]
    assert "confirm" in _last_buttons(client)
    return run_id


def _pending(bot: VaaniFlowTelegramBot, run_id: UUID) -> Any:
    return bot.repositories.pending_confirmations.list_by_run(run_id=run_id)[-1]


def test_requester_confirms_their_own_run_and_is_recorded() -> None:
    bot, client = _bot()
    run_id = _confirmation_run(bot, client)
    _send(bot, _cb(ASHA_ID, confirm_data(run_id, "yes")))
    confirmation = _pending(bot, run_id)
    assert confirmation.status is ConfirmationStatus.CONFIRMED
    assert confirmation.confirmed_by == ASHA.principal_id
    assert confirmation.confirmed_actor == ASHA
    assert _writes(bot) == (0, 0, 0)  # confirmation never executes


@pytest.mark.parametrize("user", [BILAL_ID, AUDITOR_ID, OPERATOR_ID, UNKNOWN_ID])
def test_other_users_cannot_confirm(user: int) -> None:
    bot, client = _bot()
    run_id = _confirmation_run(bot, client)
    _send(bot, _cb(user, confirm_data(run_id, "yes")))
    answer = _answer(client)
    assert "FORBIDDEN" in answer or "not on this bot's allowlist" in answer
    confirmation = _pending(bot, run_id)
    assert confirmation.status is ConfirmationStatus.REQUESTED and confirmation.confirmed_by is None


def test_stale_or_escalated_confirmation_changes_nothing() -> None:
    bot, client = _bot()
    run_id = _confirmation_run(bot, client)
    _send(bot, _cb(ASHA_ID, confirm_data(run_id, "no")))
    assert _pending(bot, run_id).status is ConfirmationStatus.DECLINED
    _send(bot, _cb(ASHA_ID, confirm_data(run_id, "yes")))  # stale click
    assert _pending(bot, run_id).status is ConfirmationStatus.DECLINED

    bot2, client2 = _bot()
    run_2 = _confirmation_run(bot2, client2)
    bot2.orchestrator.escalate(run_id=run_2, reason="x", actor=OPERATOR, now=T)
    _send(bot2, _cb(ASHA_ID, confirm_data(run_2, "yes")))
    assert _pending(bot2, run_2).status is ConfirmationStatus.SUPERSEDED
    run = bot2.repositories.runs.get_by_id(run_id=run_2)
    assert run is not None and run.status is VoiceRunStatus.HANDOFF
    assert _writes(bot2) == (0, 0, 0)


# --------------------------------------------------------------------------- #
# Callback integrity and error isolation
# --------------------------------------------------------------------------- #

_U = str(uuid4())
MALFORMED = [
    "reject",
    "reject:",
    f"reject:{encode_id(uuid4())}",
    "approve",
    "approve:",
    "approve:not-a-uuid",
    f"approve:{_U}:{_U}",  # raw UUIDs are not the button format
    "clarify",
    "clarify:not-a-uuid",
    f"clarify:{_U}",
    "confirm",
    "confirm:not-a-uuid",
    f"confirm:{encode_id(uuid4())}:maybe",
    "unknown-command",
    "extra:unexpected:parts",
    "cmd:rm",
    "cmd:demo:extra",
    "",
    "x" * 65,
    None,
    12345,
    ["approve"],
]


@pytest.mark.parametrize("data", MALFORMED)
def test_malformed_callback_is_answered_and_never_reaches_business_logic(
    data: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot, client = _bot()

    def forbidden(*_: Any, **__: Any) -> Any:
        raise AssertionError("business logic reached with malformed callback data")

    for name in ("approve", "reject", "confirm", "process_text", "start_run"):
        monkeypatch.setattr(bot.orchestrator, name, forbidden)
    _send(bot, _cb(OWNER_ID, data))
    assert _answer(client) == "This button is not valid."
    assert bot.active_runs == {}


def test_callback_codec_is_strict_and_fits_telegram_limits() -> None:
    run_id, approval_id = uuid4(), uuid4()
    for data in (
        approve_data(run_id, approval_id),
        reject_data(run_id, approval_id),
        clarify_data(run_id),
        confirm_data(run_id, "yes"),
    ):
        assert len(data.encode()) <= 64 and parse_callback(data) is not None
    parsed = parse_callback(approve_data(run_id, approval_id))
    assert parsed is not None and (parsed.run_id, parsed.approval_id) == (run_id, approval_id)
    assert decode_id(encode_id(run_id)) == run_id
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    encoded = encode_id(run_id)
    flipped = alphabet[alphabet.index(encoded[-1]) ^ 1]  # same bytes, non-canonical text
    assert decode_id(encoded[:-1] + flipped) is None
    assert decode_id("A" * 21) is None and decode_id("!" * 22) is None


def test_polling_loop_survives_malformed_failing_and_hostile_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot, client = _bot()
    calls = {"n": 0}

    async def get_updates(offset: int = 0, timeout: int = 25) -> list[dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                {"update_id": 1, **_cb(OWNER_ID, "reject:abc")},
                {"update_id": 2, "callback_query": {"id": "q"}},  # no message, no data
                {"update_id": 3, "message": {"text": "no chat"}},
                {"update_id": 4, **_msg(OWNER_ID, KUMAR)},  # backend explodes below
                {"update_id": 5, **_msg(OWNER_ID, "/start")},
            ]
        if calls["n"] == 2:
            raise TelegramAPIError("Telegram getUpdates failed: ReadTimeout", transient=True)
        raise asyncio.CancelledError

    def explode(**_: Any) -> Any:
        raise RuntimeError("backend failure")

    monkeypatch.setattr(client, "get_updates", get_updates)
    monkeypatch.setattr(bot.orchestrator, "process_text", explode)
    _run(bot.start_polling())  # returns only on cancellation

    texts = [m["text"] for m in client.sent_messages]
    assert any("internal error" in t for t in texts)  # the failing update was reported
    assert any("Welcome to VaaniFlow" in t for t in texts)  # and later updates still ran
    assert calls["n"] == 3


# --------------------------------------------------------------------------- #
# Secrets
# --------------------------------------------------------------------------- #


def _failing_client(handler: Any) -> TelegramClient:
    return TelegramClient(
        token=TOKEN, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(401, json={"ok": False, "description": "Unauthorized"}),
        lambda request: httpx.Response(500, text=f"upstream error for {request.url}"),
        lambda request: httpx.Response(
            200, json={"ok": False, "description": f"bad token {TOKEN}"}
        ),
        lambda request: httpx.Response(200, text="not json"),
    ],
)
def test_telegram_api_errors_never_contain_the_token(
    handler: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client = _failing_client(handler)
    bot = VaaniFlowTelegramBot(
        token=TOKEN, client=client, identity=TelegramIdentityProvider(ALLOWLIST)
    )
    with pytest.raises(TelegramAPIError) as raised:
        _run(bot.start_polling())
    assert TOKEN not in str(raised.value) and TOKEN not in repr(raised.value)
    error = raised.value
    assert error.__cause__ is None and (error.__context__ is None or error.__suppress_context__)
    assert TOKEN not in caplog.text  # includes httpx's own request log lines


def test_network_error_text_with_the_token_is_redacted(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    caplog.set_level(logging.DEBUG)
    with pytest.raises(TelegramAPIError) as raised:
        _run(_failing_client(handler).send_message(1, "hi"))
    assert raised.value.transient and TOKEN not in str(raised.value)


def test_token_never_reaches_logs_users_traces_or_audit(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.DEBUG)
    bot, client = _bot()
    run_a, approval_a = _requested(bot, ASHA_ID)
    _send(bot, _cb(OWNER_ID, approve_data(run_a, approval_a)))

    # A backend exception whose text happens to carry the token is logged redacted.
    def leak(**_: Any) -> Any:
        raise RuntimeError(f"request to https://api.telegram.org/bot{TOKEN}/sendMessage failed")

    monkeypatch.setattr(bot.orchestrator, "process_text", leak)
    _send(bot, _msg(BILAL_ID, KUMAR))
    logging.getLogger("vaaniflow.telegram").exception("forced", exc_info=RuntimeError(TOKEN))

    assert TOKEN not in caplog.text and "<redacted>" in caplog.text
    user_facing = [m["text"] for m in client.sent_messages + client.edited_messages]
    user_facing += [a["text"] or "" for a in client.answered_callbacks]
    assert all(TOKEN not in text for text in user_facing)
    stored = [r.model_dump_json() for r in bot.repositories.runs.list_all()]
    stored += [
        trace.model_dump_json()
        for r in bot.repositories.runs.list_all()
        if (trace := bot.repositories.traces.get_trace(run_id=r.run_id)) is not None
    ]
    stored.append(_approval(bot, approval_a).model_dump_json())
    assert all(TOKEN not in text for text in stored)
    assert redact(f"x {TOKEN} y", TOKEN) == "x <redacted> y"


def test_error_boundary_redacts_even_without_the_log_filter(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each layer protects the token on its own: no reliance on the filter alone."""
    caplog.set_level(logging.DEBUG)
    bot, _ = _bot()
    monkeypatch.setattr(logging.getLogger("vaaniflow.telegram"), "filters", [])

    def leak(**_: Any) -> Any:
        raise RuntimeError(f"request to https://api.telegram.org/bot{TOKEN}/sendMessage failed")

    monkeypatch.setattr(bot.orchestrator, "process_text", leak)
    _send(bot, _msg(BILAL_ID, KUMAR))
    assert "RuntimeError" in caplog.text and TOKEN not in caplog.text
