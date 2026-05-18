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
