"""
Telegram identity, callback integrity and secret hygiene (ADR-022, Phase 2).

* Identity: a Telegram numeric user id is looked up in an explicit allowlist
  (``TELEGRAM_PRINCIPALS``) and mapped to an existing VaaniFlow ``Principal``.
  Unknown ids authenticate no one; usernames, display names, chat ids and
  callback data never contribute identity or roles.
* Callbacks: ``callback_data`` is untrusted input. It is parsed against a closed
  grammar, ids are strict 22-character base64url UUIDs (so every button fits
  Telegram's 64-byte callback limit), and nothing in it is identity.
* Secrets: Telegram API failures are re-raised as ``TelegramAPIError`` with the
  bot token removed, and a logging filter redacts the token from every record of
  the adapter's and httpx's loggers.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from vaaniflow.config.principals import parse_principal_map
from vaaniflow.domain.models.principal import Principal

TELEGRAM_PRINCIPALS_ENV = "TELEGRAM_PRINCIPALS"
TELEGRAM_AUTHENTICATION_METHOD = "telegram-allowlist"
_TELEGRAM_USER_ID = re.compile(r"[1-9][0-9]{0,19}")


class TelegramIdentityProvider:
    """Explicit allowlist: Telegram user id → Principal. Unknown ids → None."""

    def __init__(self, principals: Mapping[int, Principal] | None = None) -> None:
        self._principals: dict[int, Principal] = {}
        for user_id, principal in (principals or {}).items():
            if type(user_id) is not int or user_id <= 0:
                raise ValueError(f"Telegram user ids must be positive integers, got {user_id!r}.")
            if principal.authentication_method != TELEGRAM_AUTHENTICATION_METHOD:
                raise ValueError(
                    "Telegram principals must use authentication_method "
                    f"{TELEGRAM_AUTHENTICATION_METHOD!r}."
                )
            if principal.synthetic:
                raise ValueError("A synthetic principal cannot be allowlisted for Telegram.")
            self._principals[user_id] = principal

    @property
    def has_principals(self) -> bool:
        return bool(self._principals)

    def authenticate(self, telegram_user_id: object) -> Principal | None:
        # bool is an int subclass; reject it and anything that is not a plain int.
        if type(telegram_user_id) is not int:
            return None
        return self._principals.get(telegram_user_id)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> TelegramIdentityProvider:
        """
        ``TELEGRAM_PRINCIPALS`` = ``{"<telegram user id>": {"actor_id": "<uuid>",
        "name": "...", "roles": ["OWNER"]}}``. Unset → nobody is allowlisted.
        A malformed value raises so the bot refuses to start.
        """
        raw = (
            (environ if environ is not None else os.environ)
            .get(TELEGRAM_PRINCIPALS_ENV, "")
            .strip()
        )
        if not raw:
            return cls()
        parsed = parse_principal_map(
            raw,
            source=TELEGRAM_PRINCIPALS_ENV,
            authentication_method=TELEGRAM_AUTHENTICATION_METHOD,
        )
        principals: dict[int, Principal] = {}
        for key, principal in parsed.items():
            if not _TELEGRAM_USER_ID.fullmatch(key):
                raise ValueError(
                    f"{TELEGRAM_PRINCIPALS_ENV} keys must be numeric Telegram user ids, "
                    f"got {key!r}."
                )
            principals[int(key)] = principal
        return cls(principals)


# --------------------------------------------------------------------------- #
# Callback grammar
# --------------------------------------------------------------------------- #

_MAX_CALLBACK_BYTES = 64  # Telegram Bot API limit for callback_data
_COMMANDS = frozenset({"demo", "bench", "status"})
_CONFIRM_REPLIES = {"yes": "yes", "no": "no"}


def encode_id(value: UUID) -> str:
    """A UUID as 22 base64url characters (no padding)."""
    return base64.urlsafe_b64encode(value.bytes).rstrip(b"=").decode("ascii")


def decode_id(text: str) -> UUID | None:
    """Inverse of ``encode_id``; None unless ``text`` is exactly a canonical encoding."""
    if len(text) != 22 or not re.fullmatch(r"[A-Za-z0-9_-]{22}", text):
        return None
    try:
        raw = base64.urlsafe_b64decode(text + "==")
    except (binascii.Error, ValueError):
        return None
    if len(raw) != 16:
        return None
    value = UUID(bytes=raw)
    return value if encode_id(value) == text else None


@dataclass(frozen=True)
class CallbackAction:
    """A parsed callback. Carries only targets, never identity, role or ownership."""

    action: str  # "cmd" | "approve" | "reject" | "clarify" | "confirm"
    command: str | None = None
    run_id: UUID | None = None
    approval_id: UUID | None = None
    reply: str | None = None


def approve_data(run_id: UUID, approval_id: UUID) -> str:
    return f"approve:{encode_id(run_id)}:{encode_id(approval_id)}"


def reject_data(run_id: UUID, approval_id: UUID) -> str:
    return f"reject:{encode_id(run_id)}:{encode_id(approval_id)}"


def clarify_data(run_id: UUID) -> str:
    return f"clarify:{encode_id(run_id)}"


def confirm_data(run_id: UUID, reply: str) -> str:
    return f"confirm:{encode_id(run_id)}:{_CONFIRM_REPLIES[reply]}"


def parse_callback(data: object) -> CallbackAction | None:
    """Parse untrusted ``callback_data``; None for anything outside the grammar."""
    if not isinstance(data, str) or not data or len(data.encode()) > _MAX_CALLBACK_BYTES:
        return None
    parts = data.split(":")
    verb, args = parts[0], parts[1:]
    if verb == "cmd" and len(args) == 1 and args[0] in _COMMANDS:
        return CallbackAction(action="cmd", command=args[0])
    if verb in {"approve", "reject"} and len(args) == 2:
        run_id, approval_id = decode_id(args[0]), decode_id(args[1])
        if run_id and approval_id:
            return CallbackAction(action=verb, run_id=run_id, approval_id=approval_id)
        return None
    if verb == "clarify" and len(args) == 1:
        run_id = decode_id(args[0])
        return CallbackAction(action="clarify", run_id=run_id) if run_id else None
    if verb == "confirm" and len(args) == 2 and args[1] in _CONFIRM_REPLIES:
        run_id = decode_id(args[0])
        return CallbackAction(action="confirm", run_id=run_id, reply=args[1]) if run_id else None
    return None


# --------------------------------------------------------------------------- #
# Secret hygiene
# --------------------------------------------------------------------------- #

_BOT_TOKEN_PATTERN = re.compile(r"\d{5,}:[A-Za-z0-9_-]{20,}")
REDACTED = "<redacted>"


def redact(text: str, token: str | None = None) -> str:
    """Remove the bot token (and anything shaped like one) from ``text``."""
    if token:
        text = text.replace(token, REDACTED)
    return _BOT_TOKEN_PATTERN.sub(REDACTED, text)


class TokenRedactingFilter(logging.Filter):
    """Redacts the bot token from a record's message and formatted exception."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage(), self._token)
        record.args = ()
        if record.exc_info:
            formatter = logging.Formatter()
            record.exc_text = redact(formatter.formatException(record.exc_info), self._token)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text, self._token)
        return True


_REDACTED_LOGGERS = (
    "vaaniflow.telegram",
    "httpx",
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
)


def install_token_redaction(token: str) -> None:
    """Attach a redacting filter (once per token) to the adapter's and httpx's loggers."""
    for name in _REDACTED_LOGGERS:
        target = logging.getLogger(name)
        if not any(
            isinstance(f, TokenRedactingFilter) and f._token == token for f in target.filters
        ):
            target.addFilter(TokenRedactingFilter(token))
