from unittest.mock import AsyncMock

import pytest

from prbot.domain.tracking.value_objects import MessageRef
from prbot.integration.slack.gateway import (
    SlackGateway,
    encode_ref,
    flatten_attachment_text,
)


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

    async def test_fetch_channel_history_includes_attachment_text(
        self, gateway: SlackGateway, mock_client: AsyncMock
    ) -> None:
        mock_client.conversations_history.return_value = {
            "messages": [
                {
                    "ts": "1.0",
                    "text": "look at this slack message",
                    "attachments": [
                        {
                            "is_msg_unfurl": True,
                            "from_url": "https://x.slack.com/archives/C/p1",
                            "text": "see https://github.com/o/r/pull/42",
                        }
                    ],
                }
            ],
            "has_more": False,
        }

        items = [item async for item in gateway.fetch_channel_history("C123", "T1")]

        assert len(items) == 1
        assert "github.com/o/r/pull/42" in items[0].text
        assert "look at this slack message" in items[0].text

    async def test_fetch_channel_history_yields_attachment_only_message(
        self, gateway: SlackGateway, mock_client: AsyncMock
    ) -> None:
        mock_client.conversations_history.return_value = {
            "messages": [
                {
                    "ts": "1.0",
                    "text": "",
                    "attachments": [{"text": "see https://github.com/o/r/pull/9"}],
                }
            ],
            "has_more": False,
        }

        items = [item async for item in gateway.fetch_channel_history("C123", "T1")]

        assert len(items) == 1
        assert "github.com/o/r/pull/9" in items[0].text


class TestFlattenAttachmentText:
    def test_returns_empty_for_no_attachments(self) -> None:
        assert flatten_attachment_text(None) == ""
        assert flatten_attachment_text([]) == ""

    def test_concatenates_string_fields(self) -> None:
        result = flatten_attachment_text(
            [{"text": "alpha", "fallback": "beta", "title_link": "https://x"}]
        )
        assert "alpha" in result
        assert "beta" in result
        assert "https://x" in result

    def test_skips_attachments_whose_from_url_is_a_pr(self) -> None:
        result = flatten_attachment_text(
            [
                {
                    "from_url": "https://github.com/o/r/pull/1",
                    "text": "should be skipped",
                },
                {"text": "see https://github.com/o/r/pull/2"},
            ]
        )
        assert "should be skipped" not in result
        assert "github.com/o/r/pull/2" in result

    def test_ignores_non_string_values(self) -> None:
        result = flatten_attachment_text([{"text": "keep", "id": 7, "nested": {"a": "drop"}}])
        assert result == "keep"

    def test_tolerates_malformed_entries(self) -> None:
        assert flatten_attachment_text([None, "string", {"text": "ok"}]) == "ok"
