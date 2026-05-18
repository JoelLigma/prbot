import logging
import re

from fastapi import FastAPI, Request
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from slack_bolt.context.ack.async_ack import AsyncAck
from slack_bolt.context.respond.async_respond import AsyncRespond
from slack_sdk.web.async_client import AsyncWebClient
from starlette.responses import Response

from prbot.application.commands import CommandDispatcher
from prbot.application.tracking.backfill_missed_messages import (
    BackfillMissedMessages,
    ChannelDescriptor,
)
from prbot.application.tracking.handle_incoming_message import HandleIncomingMessage
from prbot.config import SlackConfig
from prbot.domain.tracking.ports import ChannelCursorPort, ReactionPort
from prbot.integration.slack.gateway import INTEGRATION_ID, SlackGateway, encode_ref

logger = logging.getLogger(__name__)

_PR_URL_REGEX = re.compile(r"github\.com/[^/\s]+/[^/\s]+/pull/\d+")


class SlackIntegration:
    """Slack integration: listens for messages via Slack Events API and adds emoji reactions."""

    def __init__(
        self,
        config: SlackConfig,
        handle_incoming_message: HandleIncomingMessage,
        cursor_repo: ChannelCursorPort,
        backfill: BackfillMissedMessages,
        command_dispatcher: CommandDispatcher,
    ) -> None:
        self._config = config
        self._handle_incoming_message = handle_incoming_message
        self._cursor_repo = cursor_repo
        self._backfill = backfill
        self._dispatcher = command_dispatcher
        self._bolt_app = AsyncApp(
            token=config.bot_token,
            signing_secret=config.signing_secret,
        )
        self._client = AsyncWebClient(token=config.bot_token)
        self._gateway = SlackGateway(client=self._client)
        self._setup_events()
        self._setup_commands()

    def _setup_events(self) -> None:
        @self._bolt_app.event("message")
        async def on_message(event: dict[str, object]) -> None:
            text = str(event.get("text", ""))
            channel = str(event.get("channel", ""))
            ts = str(event.get("ts", ""))
            team = str(event.get("team", ""))
            logger.info("Slack message in %s: %s", channel, text[:100])

            # Always advance the cursor, even for non-PR messages
            if channel and ts:
                await self._cursor_repo.upsert_cursor(INTEGRATION_ID, channel, ts)

            if not _PR_URL_REGEX.search(text):
                return

            message_ref = encode_ref(channel, ts)
            scope_keys = build_scope_keys(team=team, channel=channel)
            logger.info("Found PR URL in message, processing %s", message_ref.ref)
            await self._handle_incoming_message.execute(
                message_ref=message_ref, text=text, scope_keys=scope_keys
            )

    def _setup_commands(self) -> None:
        @self._bolt_app.command("/prbot")
        async def on_command(
            ack: AsyncAck, command: dict[str, object], respond: AsyncRespond
        ) -> None:
            await ack()

            text = str(command.get("text", "")).strip()
            team = str(command.get("team_id", ""))
            channel = str(command.get("channel_id", ""))
            scope_keys = build_scope_keys(team=team, channel=channel)

            parts = text.split()
            subcommand = parts[0].lower() if parts else "help"

            try:
                response = await self._dispatcher.dispatch(subcommand, parts[1:], scope_keys)
            except Exception:
                logger.exception("Error handling /prbot command: %s", text)
                response = "Something went wrong processing that command."

            await respond(response)

    @property
    def integration_id(self) -> str:
        return INTEGRATION_ID

    def reaction_port(self) -> ReactionPort:
        return self._gateway

    def register_routes(self, app: FastAPI) -> None:
        handler = AsyncSlackRequestHandler(self._bolt_app)

        @app.post("/slack/events")
        async def slack_events(req: Request) -> Response:
            """Slack events endpoint — handled by slack-bolt via ASGI adapter."""
            return await handler.handle(req)

    async def start(self) -> None:
        channels = await self._gateway.list_bot_channels()
        descriptors = [ChannelDescriptor(channel_id=ch.id, team_id=ch.team_id) for ch in channels]
        await self._backfill.execute(
            channels=descriptors,
            fetch_history=lambda ch, oldest: self._gateway.fetch_channel_history(
                channel=ch.channel_id, team_id=ch.team_id, oldest=oldest
            ),
        )

    async def stop(self) -> None:
        pass


def build_scope_keys(team: str, channel: str) -> list[str]:
    """Build scope keys for Slack, most-specific first.

    Scope key format: <integration_id>/<workspace_id>[/<channel_id>]
    """
    iid = INTEGRATION_ID
    keys: list[str] = []
    if team and channel:
        keys.append(f"{iid}/{team}/{channel}")
    if team:
        keys.append(f"{iid}/{team}")
    keys.append(iid)
    return keys
