import logging
import time
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass

from slack_sdk.web.async_client import AsyncWebClient

from prbot.application.tracking.backfill_missed_messages import HistoryItem
from prbot.domain.tracking.value_objects import MessageRef

logger = logging.getLogger(__name__)

INTEGRATION_ID = "slack"


def encode_ref(channel: str, ts: str) -> MessageRef:
    """Encode a Slack channel and timestamp into a MessageRef."""
    return MessageRef(integration_id=INTEGRATION_ID, ref=f"{channel}:{ts}")


def seed_cursor() -> str:
    """Return a Unix float timestamp for the current time — Slack's cursor format."""
    return f"{time.time():.6f}"


def decode_ref(message_ref: MessageRef) -> tuple[str, str]:
    """Decode a Slack MessageRef into (channel, timestamp)."""
    channel, ts = message_ref.ref.split(":", 1)
    return channel, ts


@dataclass(frozen=True)
class ChannelInfo:
    """Minimal info about a Slack channel the bot is a member of."""

    id: str
    team_id: str


class SlackGateway:
    """Concrete adapter: manages Slack emoji reactions via the Slack Web API."""

    def __init__(self, client: AsyncWebClient) -> None:
        self._client = client

    @staticmethod
    def _resolve_emoji_name(emoji: str) -> str:
        """Resolve an emoji reference to a Slack-compatible name.

        Slack's reactions API requires emoji names (e.g. "headstone"), not
        Unicode characters.  If the value is already ASCII it is assumed to
        be a name.  Otherwise, derive the name from the Unicode character
        name (e.g. 🪦 → "headstone").
        """
        if emoji.isascii():
            return emoji

        # Use the Unicode name of the first character, lowercased with
        # spaces replaced by underscores — this matches Slack's naming
        # convention for most standard emoji.
        try:
            return unicodedata.name(emoji[0]).lower().replace(" ", "_").replace("-", "_")
        except ValueError:
            return emoji

    async def add_reaction(
        self,
        message_ref: MessageRef,
        emoji: str,
        fallback_emoji: str | None = None,
    ) -> None:
        channel, timestamp = decode_ref(message_ref)
        if await self._try_react(channel, timestamp, emoji):
            return
        if fallback_emoji and await self._try_react(channel, timestamp, fallback_emoji):
            logger.info(
                "Used fallback emoji %r for %s:%s (primary %r unavailable)",
                fallback_emoji,
                channel,
                timestamp,
                emoji,
            )

    async def _try_react(self, channel: str, timestamp: str, emoji: str) -> bool:
        """Add a reaction, swallowing benign failures. Returns True on success."""
        try:
            await self._client.reactions_add(
                channel=channel,
                timestamp=timestamp,
                name=self._resolve_emoji_name(emoji),
            )
            return True
        except Exception as exc:
            msg = str(exc)
            if "already_reacted" in msg:
                logger.debug("Already reacted with %s", emoji)
                return True
            if "invalid_name" in msg or "no_reaction" in msg:
                logger.warning("Unknown emoji %r in workspace for %s:%s", emoji, channel, timestamp)
                return False
            raise

    async def list_bot_channels(self) -> list[ChannelInfo]:
        """List all channels the bot is a member of, using cursor-based pagination."""
        channels: list[ChannelInfo] = []
        cursor: str | None = None

        while True:
            resp = await self._client.users_conversations(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
            )
            for ch in resp.get("channels", []):
                channels.append(
                    ChannelInfo(
                        id=ch["id"],
                        team_id=ch.get("shared_team_ids", [ch.get("context_team_id", "")])[0]
                        if ch.get("shared_team_ids")
                        else ch.get("context_team_id", ""),
                    )
                )

            next_cursor = resp.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                break
            cursor = next_cursor

        return channels

    async def fetch_channel_history(
        self,
        channel: str,
        team_id: str,
        oldest: str | None = None,
    ) -> AsyncIterator[HistoryItem]:
        """Fetch messages from a channel, optionally since a given timestamp."""
        cursor: str | None = None

        while True:
            resp = await self._client.conversations_history(
                channel=channel,
                limit=200,
                oldest=oldest,
                cursor=cursor,
            )
            for msg in resp.get("messages", []):
                text = msg.get("text", "")
                ts = msg.get("ts", "")
                if text and ts:
                    yield HistoryItem(
                        text=text,
                        ts=ts,
                        channel_id=channel,
                        team_id=team_id,
                    )

            if not resp.get("has_more", False):
                break
            next_cursor = resp.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                break
            cursor = next_cursor
