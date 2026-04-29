import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import time_machine

from prbot.application.tracking.backfill_missed_messages import (
    BackfillMissedMessages,
    ChannelDescriptor,
    HistoryItem,
)
from prbot.application.tracking.handle_incoming_message import HandleIncomingMessage
from prbot.domain.tracking.value_objects import MessageRef, PRInfo
from tests.conftest import (
    FakeCursorRepo,
    FakeEmojiConfigResolver,
    FakePRRepository,
    FakePRSource,
    FakeReactions,
    FakeScopeSettingsRepo,
    FakeUserExclusionRepo,
)


def _build_ref(channel: str, ts: str) -> MessageRef:
    return MessageRef(integration_id="slack", ref=f"{channel}:{ts}")


def _build_scope_keys(team: str, channel: str) -> list[str]:
    keys: list[str] = []
    if team and channel:
        keys.append(f"slack/{team}/{channel}")
    if team:
        keys.append(f"slack/{team}")
    keys.append("slack")
    return keys


def _make_backfill(
    cursor_repo: FakeCursorRepo,
    pr_repo: FakePRRepository | None = None,
    reactions: FakeReactions | None = None,
) -> BackfillMissedMessages:
    pr_info = PRInfo(state="closed", merged=True, reviews=())
    source = FakePRSource(pr_info)
    reactions = reactions or FakeReactions()
    pr_repo = pr_repo or FakePRRepository()
    resolver = FakeEmojiConfigResolver()

    handle = HandleIncomingMessage(
        sources=[source],
        reactions=reactions,
        pr_repository=pr_repo,
        emoji_resolver=resolver,
        user_exclusions=FakeUserExclusionRepo(),
        scope_settings=FakeScopeSettingsRepo(),
    )
    return BackfillMissedMessages(
        integration_id="slack",
        cursor_repo=cursor_repo,
        handle_incoming_message=handle,
        build_message_ref=_build_ref,
        build_scope_keys=_build_scope_keys,
        seed_cursor=lambda: f"{time.time():.6f}",
    )


class TestBackfillMissedMessages:
    @time_machine.travel(datetime(2026, 4, 1, tzinfo=UTC))
    async def test_seeds_cursor_on_first_boot(self) -> None:
        cursor_repo = FakeCursorRepo()
        backfill = _make_backfill(cursor_repo)

        channels = [ChannelDescriptor(channel_id="C1", team_id="T1")]

        async def no_history(ch: ChannelDescriptor, oldest: str) -> AsyncIterator[HistoryItem]:
            return
            yield  # make it an async generator

        await backfill.execute(channels=channels, fetch_history=no_history)

        cursor = await cursor_repo.get_cursor("slack", "C1")
        expected_ts = datetime(2026, 4, 1, tzinfo=UTC).timestamp()
        assert cursor == f"{expected_ts:.6f}"

    async def test_processes_missed_pr_messages(self) -> None:
        cursor_repo = FakeCursorRepo()
        cursor_repo.cursors[("slack", "C1")] = "1000.000000"

        pr_repo = FakePRRepository()
        reactions = FakeReactions()
        backfill = _make_backfill(cursor_repo, pr_repo=pr_repo, reactions=reactions)

        channels = [ChannelDescriptor(channel_id="C1", team_id="T1")]

        async def history_with_pr(ch: ChannelDescriptor, oldest: str) -> AsyncIterator[HistoryItem]:
            yield HistoryItem(
                text="check https://github.com/octocat/hello/pull/42",
                ts="1001.000000",
                channel_id="C1",
                team_id="T1",
            )

        await backfill.execute(channels=channels, fetch_history=history_with_pr)

        # Should have processed the PR
        assert len(pr_repo.stored) == 1
        assert pr_repo.stored[0].pr_url.number == 42

        # Should have added a reaction
        assert len(reactions.added) == 1

        # Cursor should have advanced
        cursor = await cursor_repo.get_cursor("slack", "C1")
        assert cursor == "1001.000000"

    async def test_skips_non_pr_messages(self) -> None:
        cursor_repo = FakeCursorRepo()
        cursor_repo.cursors[("slack", "C1")] = "1000.000000"

        pr_repo = FakePRRepository()
        backfill = _make_backfill(cursor_repo, pr_repo=pr_repo)

        channels = [ChannelDescriptor(channel_id="C1", team_id="T1")]

        async def history_no_pr(ch: ChannelDescriptor, oldest: str) -> AsyncIterator[HistoryItem]:
            yield HistoryItem(
                text="just a regular message",
                ts="1001.000000",
                channel_id="C1",
                team_id="T1",
            )

        await backfill.execute(channels=channels, fetch_history=history_no_pr)

        # No PRs should be tracked
        assert len(pr_repo.stored) == 0

        # But cursor should still advance
        cursor = await cursor_repo.get_cursor("slack", "C1")
        assert cursor == "1001.000000"

    @time_machine.travel(datetime(2026, 4, 3, tzinfo=UTC))
    async def test_advances_cursor_on_empty_history(self) -> None:
        cursor_repo = FakeCursorRepo()
        cursor_repo.cursors[("slack", "C1")] = "1000.000000"
        backfill = _make_backfill(cursor_repo)

        channels = [ChannelDescriptor(channel_id="C1", team_id="T1")]

        async def empty_history(ch: ChannelDescriptor, oldest: str) -> AsyncIterator[HistoryItem]:
            return
            yield

        await backfill.execute(channels=channels, fetch_history=empty_history)

        # Cursor should advance to "now" even with no messages
        cursor = await cursor_repo.get_cursor("slack", "C1")
        expected_ts = datetime(2026, 4, 3, tzinfo=UTC).timestamp()
        assert cursor == f"{expected_ts:.6f}"

    async def test_handles_empty_channel_list(self) -> None:
        cursor_repo = FakeCursorRepo()
        backfill = _make_backfill(cursor_repo)

        async def unreachable(ch: ChannelDescriptor, oldest: str) -> AsyncIterator[HistoryItem]:
            raise AssertionError("Should not be called")
            yield

        await backfill.execute(channels=[], fetch_history=unreachable)
