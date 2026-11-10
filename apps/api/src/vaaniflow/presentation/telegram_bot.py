"""
Telegram adapter for VaaniFlow (presentation layer only).

Identity: allowlisted Telegram users → Principals (``telegram_security``).
State: by default the bot uses the same application container as the HTTP API
(``api.dependencies.get_container``), so one process has one coherent state.
Rendering: ``telegram_views`` projects actual backend state; nothing is fixed.
Voice: Telegram audio → FFmpeg → WAV → ``VoiceIntakeService`` (ingest,
preprocess, configured ASR provider) → the same pipeline as typed text.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from vaaniflow.application.services.orchestrator import (
    ApprovalFlowError,
    VoiceWorkflowOrchestrator,
)
from vaaniflow.application.services.run_access import authorize_instruction
from vaaniflow.application.services.voice_intake import VoiceIntakeError, VoiceIntakeService
from vaaniflow.domain.models.approval import ApprovalStatus
from vaaniflow.domain.models.principal import (
    AuthorizationError,
    Permission,
    Principal,
    require_permission,
)
from vaaniflow.domain.models.tool_execution import ToolExecutionStatus
from vaaniflow.domain.models.voice_run import VoiceRunStatus
from vaaniflow.evaluation.runner import EvaluationRunner
from vaaniflow.infrastructure.audio.ffmpeg import AudioConversionError, convert_to_pcm16_wav
from vaaniflow.infrastructure.repositories.synthetic_data import (
    SYNTHETIC_BUSINESS_TIME,
    SyntheticRepositories,
)
from vaaniflow.presentation import telegram_views as views
from vaaniflow.presentation.telegram_security import (
    CallbackAction,
    TelegramIdentityProvider,
    install_token_redaction,
    parse_callback,
    redact,
)

logger = logging.getLogger("vaaniflow.telegram")


@dataclass(frozen=True)
class TelegramUser:
    """Telegram sender metadata. Never identity: only the allowlist maps users to principals."""

    user_id: int
    is_bot: bool
    first_name: str
    username: str | None = None

    @property
    def display_name(self) -> str:
        return f"@{self.username}" if self.username else self.first_name


class TelegramAPIError(RuntimeError):
    """A Telegram Bot API failure. The message never contains the bot token."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class TelegramClient:
    """Async client for the Telegram Bot HTTP API. Errors are sanitized (no token)."""

    BASE_URL = "https://api.telegram.org"

    def __init__(self, token: str, client: httpx.AsyncClient | None = None) -> None:
        if not token:
            raise ValueError("Telegram bot token cannot be empty.")
        self.token = token
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(timeout=45.0)

    @property
    def endpoint(self) -> str:
        return f"{self.BASE_URL}/bot{self.token}"

    @property
    def file_endpoint(self) -> str:
        return f"{self.BASE_URL}/file/bot{self.token}"

    async def close(self) -> None:
        if not self._external_client:
            await self._client.aclose()

    async def _send(self, api_method: str, url: str, **kwargs: Any) -> httpx.Response:
        """One HTTP call. Any failure becomes a TelegramAPIError without the URL/token."""
        try:
            response = await self._client.request(url=url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise TelegramAPIError(
                f"Telegram {api_method} failed: HTTP {exc.response.status_code}"
            ) from None
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramAPIError(
                f"Telegram {api_method} failed: {type(exc).__name__}", transient=True
            ) from None
        except httpx.HTTPError as exc:
            raise TelegramAPIError(f"Telegram {api_method} failed: {type(exc).__name__}") from None

    async def _call(self, api_method: str, http_method: str = "POST", **kwargs: Any) -> Any:
        response = await self._send(
            api_method, f"{self.endpoint}/{api_method}", method=http_method, **kwargs
        )
        try:
            data = response.json()
        except ValueError:
            raise TelegramAPIError(f"Telegram {api_method} returned invalid JSON") from None
        if not isinstance(data, dict) or not data.get("ok"):
            description = data.get("description") if isinstance(data, dict) else None
            raise TelegramAPIError(
                f"Telegram {api_method} error: {redact(str(description), self.token)}"
            )
        return data.get("result")

    async def get_me(self) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("getMe", "GET")
        return result

    async def get_updates(self, offset: int = 0, timeout: int = 25) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = await self._call(
            "getUpdates", "GET", params={"offset": offset, "timeout": timeout}
        )
        return result

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "HTML",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        result: dict[str, Any] = await self._call("sendMessage", json=payload)
        return result

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "HTML",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        result: dict[str, Any] = await self._call("editMessageText", json=payload)
        return result

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> bool:
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = text
        return bool(await self._call("answerCallbackQuery", json=payload))

    async def get_file(self, file_id: str) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("getFile", "GET", params={"file_id": file_id})
        return result

    async def download_file(self, file_path: str) -> bytes:
        response = await self._send(
            "downloadFile", f"{self.file_endpoint}/{file_path}", method="GET"
        )
        return response.content


class VaaniFlowTelegramBot:
    """Telegram presentation adapter over the VaaniFlow application services."""

    CANONICAL_DEMO_TEXT = (
        "Arre Suresh, Sharma Builders ko turant 200 bag Ultratech cement dispatch karo. "
        "Rate wahi lagana jo parso bataya tha—chaar sau bees rupaye per bag plus GST. "
        "Invoice bana ke mujhe WhatsApp pe approve karne bhej do."
    )

    def __init__(
        self,
        token: str,
        orchestrator: VoiceWorkflowOrchestrator | None = None,
        repositories: SyntheticRepositories | None = None,
        client: TelegramClient | None = None,
        identity: TelegramIdentityProvider | None = None,
        *,
        container: Any | None = None,
        voice_intake: VoiceIntakeService | None = None,
        ffmpeg_executable: str | None = None,
        evaluation_runner: EvaluationRunner | None = None,
    ) -> None:
        """
        By default the bot shares the HTTP API's application container (one state
        per process). ``orchestrator``/``repositories`` are for isolated tests; a
        bare ``repositories`` gets an orchestrator on the synthetic business clock.
        """
        # Unset TELEGRAM_PRINCIPALS → nobody is allowlisted; malformed → raises here.
        self.identity = identity or TelegramIdentityProvider.from_env()
        self._token = token
        if len(token) >= 8:
            install_token_redaction(token)
        if orchestrator is None and repositories is None:
            if container is None:
                from vaaniflow.api.dependencies import get_container

                container = get_container()
            orchestrator = container.orchestrator
            repositories = container.repositories
        elif orchestrator is None:
            assert repositories is not None
            orchestrator = VoiceWorkflowOrchestrator(
                repositories=repositories, clock=lambda: SYNTHETIC_BUSINESS_TIME
            )
        self.orchestrator: VoiceWorkflowOrchestrator = orchestrator
        self.repositories = repositories or orchestrator.repositories
        self.container = container
        self.client = client or TelegramClient(token=token)
        self.voice_intake = voice_intake
        self.ffmpeg_executable = ffmpeg_executable
        self.evaluation_runner = evaluation_runner or EvaluationRunner()
        # Active run per authenticated principal (never per chat): in-memory only.
        self.active_runs: dict[UUID, UUID] = {}

    # ------------------------------------------------------------------ #
    # Update dispatch and error boundary
    # ------------------------------------------------------------------ #

    async def handle_update(self, update: dict[str, Any]) -> None:
        """
        Handle one Telegram update. This is the error boundary: a failure in one
        update is logged (token-redacted) and never stops the polling loop.
        """
        update_id = update.get("update_id")
        try:
            if "message" in update:
                await self._handle_message(update["message"])
            elif "callback_query" in update:
                await self._handle_callback(update["callback_query"])
        except TelegramAPIError as exc:
            logger.warning("Telegram API error while handling update %s: %s", update_id, exc)
        except Exception as exc:  # noqa: BLE001 - per-update boundary: logged, loop survives
            logger.error(
                "Unhandled %s while handling update %s: %s",
                type(exc).__name__,
                update_id,
                redact(str(exc), self._token),
            )
            await self._notify_internal_error(update)

    async def _notify_internal_error(self, update: dict[str, Any]) -> None:
        message = update.get("message") or (update.get("callback_query") or {}).get("message")
        chat_id = (message or {}).get("chat", {}).get("id") if isinstance(message, dict) else None
        if not isinstance(chat_id, int):
            return
        try:
            await self.client.send_message(
                chat_id,
                "⚠️ An internal error occurred. Nothing was retried automatically; "
                "check the run before trying again.",
            )
        except TelegramAPIError as exc:
            logger.warning("Could not report an internal error to the chat: %s", exc)

    # ------------------------------------------------------------------ #
    # Identity (ADR-022): private chat + allowlisted Telegram user → Principal
    # ------------------------------------------------------------------ #

    def _authenticate(
        self, chat: dict[str, Any], sender: dict[str, Any]
    ) -> tuple[Principal | None, str]:
        """The allowlisted principal behind this update, or (None, reason)."""
        user_id = sender.get("id")
        if chat.get("type") != "private":
            return None, "VaaniFlow only works in a private chat with an allowlisted user."
        if type(user_id) is not int or sender.get("is_bot") or chat.get("id") != user_id:
            return None, "This update does not come from a single Telegram user."
        principal = self.identity.authenticate(user_id)
        if principal is None:
            return None, (
                f"You are not on this bot's allowlist (Telegram user id {user_id}). "
                "Nothing was done."
            )
        return principal, ""

    @staticmethod
    def _refusal(error: AuthorizationError | ApprovalFlowError) -> str:
        return f"⛔ Not done ({error.code}): {error.message}"

    async def _send(self, chat_id: int, text: str, markup: dict[str, Any] | None = None) -> None:
        await self.client.send_message(chat_id, text, reply_markup=markup)

    # ------------------------------------------------------------------ #
    # Messages
    # ------------------------------------------------------------------ #

    async def _handle_message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return
        principal, reason = self._authenticate(chat, message.get("from") or {})
        if principal is None:
            await self._send(chat_id, f"⛔ {views.esc(reason)}")
            return

        text = (message.get("text") or "").strip()
        if text.startswith(("/start", "/help")):
            await self._send_welcome(chat_id, principal)
            return
        if text.startswith("/benchmark"):
            await self._run_benchmark(chat_id)
            return
        if text.startswith("/status"):
            await self._run_status(chat_id)
            return

        # Everything below submits an instruction.
        try:
            require_permission(principal, Permission.SUBMIT_INSTRUCTION)
        except AuthorizationError as error:
            await self._send(chat_id, views.esc(self._refusal(error)))
            return

        if text.startswith("/demo"):
            await self._run_demo(chat_id, principal)
            return
        if "voice" in message or "audio" in message:
            await self._handle_voice(chat_id, principal, message.get("voice") or message["audio"])
            return
        if text:
            await self._instruct(chat_id, principal, text, new_run=False)

    async def _handle_voice(self, chat_id: int, principal: Principal, voice: Any) -> None:
        """Telegram audio → WAV → ASR → the same pipeline as text. Nothing is substituted."""
        if self.voice_intake is None:
            await self._send(
                chat_id,
                "🎙️ Voice notes are not available: no speech-to-text provider is configured "
                "(set <code>GNANI_API_KEY</code>). Please type the instruction instead.",
            )
            return
        file_id = voice.get("file_id") if isinstance(voice, dict) else None
        if not isinstance(file_id, str):
            await self._send(chat_id, "🎙️ That voice note could not be read.")
            return
        file_info = await self.client.get_file(file_id)
        raw = await self.client.download_file(str(file_info.get("file_path", "")))
        try:
            wav = await asyncio.to_thread(
                convert_to_pcm16_wav, raw, executable=self.ffmpeg_executable
            )
            voice_transcript = await asyncio.to_thread(
                self.voice_intake.transcribe_wav, wav, now=self.orchestrator.clock()
            )
        except (AudioConversionError, VoiceIntakeError) as error:
            logger.info("Voice note not transcribed: %s", error.code)
            await self._send(
                chat_id,
                f"🎙️ The voice note was not processed ({views.esc(error.code)}): "
                f"{views.esc(error.message)} Nothing was done.",
            )
            return
        transcript = voice_transcript.transcript
        await self._send(
            chat_id,
            f"🎙️ Transcribed by <code>{views.esc(transcript.provider)}</code>:\n"
            f"<i>{views.esc(transcript.text, 500)}</i>",
        )
        run = self.orchestrator.start_run(owner_id=principal.principal_id)
        self.active_runs[principal.principal_id] = run.run_id
        result = self.orchestrator.process_transcript(
            transcript=transcript, run_id=run.run_id, audio=voice_transcript.audio
        )
        text, markup = views.render_workflow(result, transcript.text)
        await self._send(chat_id, text, markup)

    async def _instruct(
        self, chat_id: int, principal: Principal, text: str, *, new_run: bool
    ) -> None:
        """
        Send text to the principal's own open run, or to a new run they own. A run
        waiting for a clarification gets the reply merged into what was asked.
        """
        run = None
        active_run_id = None if new_run else self.active_runs.get(principal.principal_id)
        if active_run_id is not None:
            run = self.repositories.runs.get_by_id(run_id=active_run_id)
        if run is not None:
            try:
                authorize_instruction(principal, run)
            except AuthorizationError as error:
                if error.code not in {"RUN_CLOSED", "RUN_ESCALATED"}:
                    await self._send(chat_id, views.esc(self._refusal(error)))
                    return
                # A settled or escalated run is never reopened: start a new one.
                run = None
        if run is None:
            run = self.orchestrator.start_run(owner_id=principal.principal_id)
            self.active_runs[principal.principal_id] = run.run_id
            result = self.orchestrator.process_text(text=text, run_id=run.run_id)
        else:
            self.active_runs[principal.principal_id] = run.run_id
            result = self.orchestrator.clarify(run_id=run.run_id, reply=text)
        transcript = result.understand_result.transcript.text if result.understand_result else text
        card, markup = views.render_workflow(result, transcript)
        await self._send(chat_id, card, markup)

    async def _send_welcome(self, chat_id: int, principal: Principal) -> None:
        voice = "available" if self.voice_intake else "not configured"
        welcome = (
            f"👋 <b>Welcome to VaaniFlow, {views.esc(principal.display_name)}!</b>\n\n"
            "Send an instruction in Hinglish or English. VaaniFlow resolves it against "
            "business records, validates it and asks for approval before anything is "
            "executed.\n\n"
            f"• 🎙️ Voice notes: {voice}\n"
            "• 🧪 /demo: run the canonical demo instruction through the real pipeline\n"
            "• 📊 /benchmark: run the evaluation scenarios now\n"
            "• ℹ️ /status: current in-memory state"
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🧪 Run demo instruction", "callback_data": "cmd:demo"}],
                [
                    {"text": "📊 Evaluation", "callback_data": "cmd:bench"},
                    {"text": "ℹ️ Status", "callback_data": "cmd:status"},
                ],
            ]
        }
        await self._send(chat_id, welcome, markup)

    # ------------------------------------------------------------------ #
    # Callbacks
    # ------------------------------------------------------------------ #

    async def _handle_callback(self, query: dict[str, Any]) -> None:
        query_id = query.get("id")
        if not isinstance(query_id, str):
            return
        message = query.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        message_id = message.get("message_id")

        # callback_data is untrusted: it names targets only, never identity or roles.
        parsed = parse_callback(query.get("data"))
        if parsed is None:
            logger.info("Rejected malformed callback data (%d chars)", len(str(query.get("data"))))
            await self.client.answer_callback_query(
                query_id, "This button is not valid.", show_alert=True
            )
            return

        principal, reason = self._authenticate(chat, query.get("from") or {})
        if principal is None or not isinstance(chat_id, int):
            await self.client.answer_callback_query(
                query_id, reason or "Not authorised.", show_alert=True
            )
            return

        try:
            await self._dispatch_callback(parsed, principal, query_id, chat_id, message_id)
        except (AuthorizationError, ApprovalFlowError) as error:
            # Authorization or stale-state refusal: nothing was changed.
            await self.client.answer_callback_query(query_id, self._refusal(error), show_alert=True)

    async def _dispatch_callback(
        self,
        parsed: CallbackAction,
        principal: Principal,
        query_id: str,
        chat_id: int,
        message_id: Any,
    ) -> None:
        if parsed.action == "cmd":
            await self.client.answer_callback_query(query_id)
            if parsed.command == "demo":
                require_permission(principal, Permission.SUBMIT_INSTRUCTION)
                await self._run_demo(chat_id, principal)
            elif parsed.command == "bench":
                await self._run_benchmark(chat_id)
            else:
                await self._run_status(chat_id)
            return

        assert parsed.run_id is not None  # guaranteed by parse_callback for run actions
        if parsed.action == "approve":
            assert parsed.approval_id is not None
            # The orchestrator enforces APPROVE (OWNER), the approval↔run binding and
            # that the approval is still pending against current state. Nothing is
            # shown as approved before it returns.
            result = self.orchestrator.approve(
                run_id=parsed.run_id, approval_id=parsed.approval_id, actor=principal
            )
            if result.approval is None or result.approval.status is not ApprovalStatus.APPROVED:
                # Stale against current state (e.g. the business snapshot changed and the
                # approval expired): nothing executed; say so instead of a receipt.
                await self.client.answer_callback_query(query_id, result.message, show_alert=True)
                return
            await self.client.answer_callback_query(query_id, "Approval recorded.")
            receipt = views.render_receipt(result, approver=principal)
            if isinstance(message_id, int):
                await self.client.edit_message_text(chat_id, message_id, receipt)
            else:
                await self._send(chat_id, receipt)
            return

        if parsed.action == "reject":
            assert parsed.approval_id is not None
            self.orchestrator.reject(
                run_id=parsed.run_id, approval_id=parsed.approval_id, actor=principal
            )
            await self.client.answer_callback_query(query_id, "Plan rejected.")
            if isinstance(message_id, int):
                await self.client.edit_message_text(
                    chat_id, message_id, views.render_rejection(parsed.run_id, principal)
                )
            return

        if parsed.action == "confirm":
            assert parsed.reply is not None
            # The orchestrator enforces CONFIRM, run ownership and that the
            # confirmation is still pending; a stale reply changes nothing.
            result = self.orchestrator.confirm(
                run_id=parsed.run_id, reply=parsed.reply, actor=principal
            )
            await self.client.answer_callback_query(query_id)
            card, markup = views.render_workflow(result, "")
            await self._send(chat_id, card, markup)
            return

        # clarify: the callback's run id is untrusted; the shared run rules decide.
        run = self.repositories.runs.get_by_id(run_id=parsed.run_id)
        if run is None:
            raise AuthorizationError("RUN_NOT_FOUND", "That run no longer exists.")
        authorize_instruction(principal, run)
        self.active_runs[principal.principal_id] = run.run_id
        await self.client.answer_callback_query(query_id)
        await self._send(
            chat_id,
            f"✍️ <i>Please send your clarification for run <code>{views.short(run.run_id)}</code>: "
            "the complete corrected instruction. It replaces the pending plan; nothing "
            "executes without a new approval.</i>",
        )

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    async def _run_demo(self, chat_id: int, principal: Principal) -> None:
        """The canonical demo instruction (a fixed input) through the real pipeline."""
        await self._send(
            chat_id,
            "🧪 <i>Demo instruction (fixed input; everything below is computed):</i>\n"
            f"<i>{views.esc(self.CANONICAL_DEMO_TEXT, 500)}</i>",
        )
        await self._instruct(chat_id, principal, self.CANONICAL_DEMO_TEXT, new_run=True)

    async def _run_benchmark(self, chat_id: int) -> None:
        """Run the evaluation suite now (isolated repositories) and show its real result."""
        suite = await asyncio.to_thread(self.evaluation_runner.run_all)
        await self._send(chat_id, views.render_benchmark(suite))

    def status_facts(self) -> dict[str, Any]:
        """Counts and configuration of this process, read from the repositories."""
        repos = self.repositories
        runs = repos.runs.list_all()
        approvals = [
            approval
            for run in runs
            for pending in repos.pending_executions.list_by_run(run_id=run.run_id)
            if (approval := repos.approvals.get_by_id(approval_id=pending.approval_id))
        ]
        executions = [
            e for run in runs for e in repos.tool_executions.list_by_run(run_id=run.run_id)
        ]
        clock_source = getattr(self.container, "business_clock_source", "injected")
        by_status: dict[str, int] = {}
        for run in runs:
            by_status[run.status.value] = by_status.get(run.status.value, 0) + 1
        return {
            "Business clock": f"{self.orchestrator.clock().isoformat()} ({clock_source})",
            "Runs": len(runs),
            "Runs by status": ", ".join(f"{k} {v}" for k, v in sorted(by_status.items())) or "none",
            "Approvals pending": sum(a.status is ApprovalStatus.REQUESTED for a in approvals),
            "Approvals approved": sum(a.status is ApprovalStatus.APPROVED for a in approvals),
            "Tool executions": len(executions),
            "UNKNOWN outcomes": sum(e.status is ToolExecutionStatus.UNKNOWN for e in executions),
            "Orders / invoices / dispatches": (
                f"{len(repos.orders.list_all())} / {len(repos.invoices.list_all())} / "
                f"{len(repos.dispatches.list_all())}"
            ),
            "Runs handed to an operator": sum(r.status is VoiceRunStatus.HANDOFF for r in runs),
            "Customers / products / quotes": (
                f"{len(repos.customers.list_all())} / {len(repos.products.list_all())} / "
                f"{len(repos.quotes.list_all())}"
            ),
            "Speech-to-text": "configured" if self.voice_intake else "not configured",
            "WhatsApp / notifications": "not supported (handed to an operator)",
        }

    async def _run_status(self, chat_id: int) -> None:
        await self._send(chat_id, views.render_status(self.status_facts()))

    # ------------------------------------------------------------------ #
    # Long polling
    # ------------------------------------------------------------------ #

    async def start_polling(self) -> None:
        """Start resilient long polling for updates."""
        try:
            bot_info = await self.client.get_me()
        except TelegramAPIError as exc:
            logger.error("Failed to connect to Telegram: %s", exc)
            raise
        username = bot_info.get("username", "unknown")
        logger.info("Connected to Telegram as @%s (ID: %s)", username, bot_info.get("id"))
        print(f"🚀 VaaniFlow Telegram Bot is live as @{username}!")
        print("Listening for voice notes and text messages (Ctrl+C to stop)...")

        offset = 0
        while True:
            try:
                updates = await self.client.get_updates(offset=offset, timeout=20)
            except asyncio.CancelledError:
                break
            except TelegramAPIError as exc:
                if not exc.transient:
                    logger.error("Polling error: %s", exc)
                    await asyncio.sleep(2.0)
                continue
            for update in updates:
                if isinstance(update.get("update_id"), int):
                    offset = max(offset, update["update_id"] + 1)
                await self.handle_update(update)  # never raises (per-update boundary)


def voice_intake_from_env(environ: dict[str, str] | None = None) -> VoiceIntakeService | None:
    """Gnani ASR when GNANI_API_KEY is set; otherwise None (voice notes are refused)."""
    env = environ if environ is not None else dict(os.environ)
    if not env.get("GNANI_API_KEY", "").strip():
        return None
    from pathlib import Path

    from vaaniflow.audio import LocalAudioPreprocessor
    from vaaniflow.infrastructure.storage.local import LocalArtifactStorage
    from vaaniflow.providers.gnani import GnaniASRProvider

    storage = LocalArtifactStorage(Path(env.get("VAANIFLOW_ARTIFACT_DIR", "artifacts")))
    return VoiceIntakeService(
        artifact_storage=storage,
        audio_preprocessor=LocalAudioPreprocessor(),
        asr_provider=GnaniASRProvider.from_environment(),
        language_hint=env.get("VAANIFLOW_ASR_LANGUAGE") or None,
    )


async def run_bot() -> None:
    """Entry point: the Telegram bot only (its own process state)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("❌ Error: TELEGRAM_BOT_TOKEN environment variable is not set.")
        print("Please export TELEGRAM_BOT_TOKEN='your_token_here' and run again.")
        return
    try:
        identity = TelegramIdentityProvider.from_env()
    except ValueError as exc:
        print(f"❌ Error: {exc}")
        return
    if not identity.has_principals:
        print("⚠️ TELEGRAM_PRINCIPALS is not set: every Telegram user will be refused.")

    bot = VaaniFlowTelegramBot(token=token, identity=identity, voice_intake=voice_intake_from_env())
    try:
        await bot.start_polling()
    finally:
        await bot.client.close()


if __name__ == "__main__":
    asyncio.run(run_bot())
