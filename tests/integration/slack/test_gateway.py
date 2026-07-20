from unittest.mock import AsyncMock

import pytest

from prbot.domain.tracking.value_objects import MessageRef
from prbot.integration.slack.gateway import SlackGateway, encode_ref


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def gateway(mock_client: AsyncMock) -> SlackGateway:
    return SlackGateway(client=mock_client)


def _msg_ref() -> MessageRef:
    return encode_ref("C123", "1234.5678")


class TestSlackGateway:
    async def test_add_reaction_calls_api(
        self, gateway: SlackGateway, mock_client: AsyncMock
    ) -> None:
        await gateway.add_reaction(_msg_ref(), "eyes")

        mock_client.reactions_add.assert_awaited_once_with(
            channel="C123", timestamp="1234.5678", name="eyes"
        )

    async def test_add_reaction_ignores_already_reacted(
        self, gateway: SlackGateway, mock_client: AsyncMock
    ) -> None:
        mock_client.reactions_add.side_effect = Exception("already_reacted")

        # Should not raise
        await gateway.add_reaction(_msg_ref(), "eyes")

    async def test_add_reaction_raises_other_errors(
        self, gateway: SlackGateway, mock_client: AsyncMock
    ) -> None:
        mock_client.reactions_add.side_effect = Exception("channel_not_found")

        with pytest.raises(Exception, match="channel_not_found"):
            await gateway.add_reaction(_msg_ref(), "eyes")

    async def test_add_reaction_ignores_deleted_message(
        self, gateway: SlackGateway, mock_client: AsyncMock
    ) -> None:
        mock_client.reactions_add.side_effect = Exception("message_not_found")

        # Should not raise — a deleted message is a dead end, not an error.
        await gateway.add_reaction(_msg_ref(), "git-approved")

    async def test_add_reaction_skips_fallback_when_message_deleted(
        self, gateway: SlackGateway, mock_client: AsyncMock
    ) -> None:
        mock_client.reactions_add.side_effect = Exception("message_not_found")

        await gateway.add_reaction(_msg_ref(), "git-approved", "\N{WHITE HEAVY CHECK MARK}")

        # No point retrying the fallback against a message that no longer exists.
        assert mock_client.reactions_add.await_count == 1

    async def test_cross_mark_resolves_to_slack_x_alias(
        self, gateway: SlackGateway, mock_client: AsyncMock
    ) -> None:
        # ❌ derives to "cross_mark", but Slack's alias is ":x:" — the resolver
        # must translate so the unicode fallback actually resolves on Slack.
        await gateway.add_reaction(_msg_ref(), "\N{CROSS MARK}")

        mock_client.reactions_add.assert_awaited_once_with(
            channel="C123", timestamp="1234.5678", name="x"
        )

    async def test_custom_primary_with_x_fallback(
        self, gateway: SlackGateway, mock_client: AsyncMock
    ) -> None:
        # Mirrors a workspace with a custom :ci_failed: emoji as primary and the
        # ❌ unicode fallback: primary works, so ❌ is never reached.
        await gateway.add_reaction(_msg_ref(), "ci_failed", "\N{CROSS MARK}")

        mock_client.reactions_add.assert_awaited_once_with(
            channel="C123", timestamp="1234.5678", name="ci_failed"
        )
