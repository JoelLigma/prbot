import pytest

from prbot.application.tracking.handle_incoming_message import HandleIncomingMessage
from prbot.domain.emoji.value_objects import EmojiConfig
from prbot.domain.tracking.value_objects import MessageRef, PRInfo, Review, ReviewState
from tests.conftest import (
    FakeEmojiConfigResolver,
    FakePRRepository,
    FakePRSource,
    FakeReactions,
    FakeScopeSettingsRepo,
    FakeUserExclusionRepo,
)


def _msg_ref() -> MessageRef:
    return MessageRef(integration_id="slack", ref="C123:1234.5678")


def _open_pr() -> PRInfo:
    return PRInfo(state="open", merged=False, reviews=())


def _approved_pr() -> PRInfo:
    return PRInfo(
        state="open",
        merged=False,
        reviews=(Review(user_login="alice", state=ReviewState.APPROVED),),
    )


class TestHandleIncomingMessage:
    @pytest.fixture
    def reactions(self) -> FakeReactions:
        return FakeReactions()

    @pytest.fixture
    def repo(self) -> FakePRRepository:
        return FakePRRepository()

    @pytest.fixture
    def resolver(self) -> FakeEmojiConfigResolver:
        return FakeEmojiConfigResolver()

    @pytest.fixture
    def exclusions(self) -> FakeUserExclusionRepo:
        return FakeUserExclusionRepo()

    @pytest.fixture
    def scope_settings(self) -> FakeScopeSettingsRepo:
        return FakeScopeSettingsRepo()

    async def test_open_pr_gets_no_reaction(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        source = FakePRSource(_open_pr())
        use_case = HandleIncomingMessage(
            [source], reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute(_msg_ref(), "Check https://github.com/o/r/pull/1")

        assert len(reactions.added) == 0
        assert len(repo.stored) == 1
        assert repo.stored[0].applied_emojis == frozenset()

    async def test_message_without_pr_url_does_nothing(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        source = FakePRSource(_open_pr())
        use_case = HandleIncomingMessage(
            [source], reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute(_msg_ref(), "Just a normal message")

        assert len(reactions.added) == 0
        assert len(repo.stored) == 0

    async def test_message_with_multiple_pr_urls(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        source = FakePRSource(_approved_pr())
        use_case = HandleIncomingMessage(
            [source], reactions, repo, resolver, exclusions, scope_settings
        )

        text = "See github.com/o/r/pull/1 and github.com/o/r/pull/2"
        await use_case.execute(_msg_ref(), text)

        assert len(reactions.added) == 2
        assert len(repo.stored) == 2

    async def test_duplicate_pr_url_only_processed_once(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        source = FakePRSource(_approved_pr())
        use_case = HandleIncomingMessage(
            [source], reactions, repo, resolver, exclusions, scope_settings
        )

        text = "github.com/o/r/pull/1 and github.com/o/r/pull/1 again"
        await use_case.execute(_msg_ref(), text)

        assert len(reactions.added) == 1

    async def test_approved_pr_gets_correct_emoji(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        source = FakePRSource(_approved_pr())
        use_case = HandleIncomingMessage(
            [source], reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute(_msg_ref(), "github.com/o/r/pull/1")

        assert reactions.added[0] == (_msg_ref(), "git-approved")

    async def test_fallback_emoji_is_passed_to_reactions_port(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        source = FakePRSource(_approved_pr())
        use_case = HandleIncomingMessage(
            [source], reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute(_msg_ref(), "github.com/o/r/pull/1")

        _, emoji, fallback = reactions.added_with_fallback[0]
        assert emoji == "git-approved"
        assert fallback == EmojiConfig.fallback_for_status("approved")

    async def test_pr_stored_in_repository(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        source = FakePRSource(_approved_pr())
        use_case = HandleIncomingMessage(
            [source], reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute(_msg_ref(), "github.com/o/r/pull/1")

        assert len(repo.stored) == 1
        tracked = repo.stored[0]
        assert tracked.pr_url.owner == "o"
        assert tracked.pr_url.repo == "r"
        assert tracked.pr_url.number == 1
        assert tracked.message_ref == _msg_ref()
        assert tracked.applied_emojis == frozenset({"git-approved"})

    async def test_custom_emoji_config(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        source = FakePRSource(_approved_pr())
        custom_resolver = FakeEmojiConfigResolver(EmojiConfig(approved="shipit"))
        use_case = HandleIncomingMessage(
            [source], reactions, repo, custom_resolver, exclusions, scope_settings
        )

        await use_case.execute(_msg_ref(), "github.com/o/r/pull/1")

        assert reactions.added[0][1] == "shipit"

    async def test_excluded_reviewer_does_not_drive_status(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        # Repro: a PR has a comment review from cursor[bot]; if cursor[bot]
        # is workspace-excluded, pasting the URL into a channel that inherits
        # that exclusion should not produce a `commented` reaction.
        pr_with_cursor_comment = PRInfo(
            state="open",
            merged=False,
            reviews=(Review(user_login="cursor[bot]", state=ReviewState.COMMENTED),),
        )
        source = FakePRSource(pr_with_cursor_comment)
        await exclusions.add("slack/T1", "cursor[bot]")
        use_case = HandleIncomingMessage(
            [source], reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute(
            _msg_ref(),
            "github.com/o/r/pull/1",
            scope_keys=["slack/T1/C123", "slack/T1", "slack"],
        )

        assert len(reactions.added) == 0
        assert repo.stored[0].applied_emojis == frozenset()

    async def test_self_review_comment_muted_on_initial_tracking(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        # Author commented on their own PR. mute_self_reviews is enabled at
        # the workspace scope. Pasting the URL into a channel that inherits
        # the mute must not produce a `commented` reaction.
        pr_with_self_comment = PRInfo(
            state="open",
            merged=False,
            reviews=(Review(user_login="bob", state=ReviewState.COMMENTED),),
            author_login="bob",
        )
        source = FakePRSource(pr_with_self_comment)
        await scope_settings.set("slack/T1", "mute_self_reviews", True)
        use_case = HandleIncomingMessage(
            [source], reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute(
            _msg_ref(),
            "github.com/o/r/pull/1",
            scope_keys=["slack/T1/C123", "slack/T1", "slack"],
        )

        assert len(reactions.added) == 0
        assert repo.stored[0].applied_emojis == frozenset()

    async def test_self_review_mute_does_not_hide_other_reviewer_comment(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        # Mute should drop only the author's COMMENTED reviews — a comment
        # from someone else should still drive the status.
        pr = PRInfo(
            state="open",
            merged=False,
            reviews=(
                Review(user_login="bob", state=ReviewState.COMMENTED),
                Review(user_login="alice", state=ReviewState.COMMENTED),
            ),
            author_login="bob",
        )
        source = FakePRSource(pr)
        await scope_settings.set("slack/T1", "mute_self_reviews", True)
        use_case = HandleIncomingMessage(
            [source], reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute(
            _msg_ref(),
            "github.com/o/r/pull/1",
            scope_keys=["slack/T1/C123", "slack/T1", "slack"],
        )

        assert reactions.added[0][1] == "speech_balloon"
