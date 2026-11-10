"""
One process, one application state: the HTTP API and the Telegram bot together.

    python -m vaaniflow.presentation.serve

Both use ``api.dependencies.get_container()``, so a run created in Telegram is
visible to ``GET /runs/{id}/audit`` and an approval made in one interface is the
state the other sees. State is in memory and lost on restart; running the API
and the bot as separate processes gives each its own, unshared state.
"""

from __future__ import annotations

import asyncio
import os

import uvicorn

from vaaniflow.api.dependencies import get_container
from vaaniflow.presentation.telegram_bot import VaaniFlowTelegramBot, voice_intake_from_env
from vaaniflow.presentation.telegram_security import TelegramIdentityProvider


async def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("❌ Error: TELEGRAM_BOT_TOKEN environment variable is not set.")
        return
    try:
        identity = TelegramIdentityProvider.from_env()
        container = get_container()  # validates VAANIFLOW_API_TOKENS and the clock now
    except ValueError as exc:
        print(f"❌ Error: {exc}")
        return
    bot = VaaniFlowTelegramBot(
        token=token, identity=identity, container=container, voice_intake=voice_intake_from_env()
    )
    server = uvicorn.Server(uvicorn.Config("vaaniflow.api.app:app", host=host, port=port))
    try:
        await asyncio.gather(server.serve(), bot.start_polling())
    finally:
        await bot.client.close()


if __name__ == "__main__":
    asyncio.run(
        serve(
            host=os.environ.get("VAANIFLOW_HOST", "127.0.0.1"),
            port=int(os.environ.get("VAANIFLOW_PORT", "8000")),
        )
    )
