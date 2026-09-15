import pytest

from prbot.application.tracking.handle_github_webhook import HandleGitHubWebhook
from prbot.domain.tracking.entities import TrackedPR
from prbot.domain.tracking.value_objects import MessageRef, PRInfo, PRUrl, Review, ReviewState
from tests.conftest import (
    FakeEmojiConfigResolver,
    FakePRRepository,
    FakePRSource,
    FakeReactions,
    FakeScopeSettingsRepo,
    FakeUserExclusionRepo,
)


def _pr_url() -> PRUrl:
    return PRUrl(owner="o", repo="r", number=1)


def _msg_ref(channel: str = "C123", ts: str = "1234.5678") -> MessageRef:
    return MessageRef(integration_id="slack", ref=f"{channel}:{ts}")


class TestHandleGitHubWebhook:
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

    async def test_webhook_adds_emoji_for_new_status(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        repo.stored.append(TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref()))
        merged_info = PRInfo(state="closed", merged=True, reviews=())
        source = FakePRSource(merged_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1)

        assert len(reactions.added) == 1
        assert reactions.added[0] == (_msg_ref(), "git-merged")

    async def test_webhook_skips_already_applied_emoji(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        repo.stored.append(
            TrackedPR(
                pr_url=_pr_url(),
                message_ref=_msg_ref(),
                applied_emojis=frozenset({"git-merged"}),
            )
        )
        merged_info = PRInfo(state="closed", merged=True, reviews=())
        source = FakePRSource(merged_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1)

        assert len(reactions.added) == 0

    async def test_webhook_no_reaction_for_open_status(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        repo.stored.append(TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref()))
        open_info = PRInfo(state="open", merged=False, reviews=())
        source = FakePRSource(open_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1)

        assert len(reactions.added) == 0

    async def test_webhook_updates_all_tracked_messages(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        for i in range(3):
            repo.stored.append(
                TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref(f"C{i}", f"{i}.0000"))
            )
        merged_info = PRInfo(state="closed", merged=True, reviews=())
        source = FakePRSource(merged_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1)

        assert len(reactions.added) == 3

    async def test_webhook_continues_past_unreachable_message(
        self,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        """A deleted message sorted first must not starve the ones after it."""
        dead = _msg_ref("C0", "dead.0000")
        alive = _msg_ref("C0", "alive.0000")
        repo.stored.append(TrackedPR(pr_url=_pr_url(), message_ref=dead))
        repo.stored.append(TrackedPR(pr_url=_pr_url(), message_ref=alive))

        class ExplodingReactions(FakeReactions):
            async def add_reaction(
                self,
                message_ref: MessageRef,
                emoji: str,
                fallback_emoji: str | None = None,
            ) -> None:
                if message_ref == dead:
                    raise RuntimeError("message_not_found")
                await super().add_reaction(message_ref, emoji, fallback_emoji)

        reactions = ExplodingReactions()
        merged_info = PRInfo(state="closed", merged=True, reviews=())
        source = FakePRSource(merged_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1)

        assert [ref for ref, _ in reactions.added] == [alive]
        by_ref = {t.message_ref: t for t in repo.stored}
        assert by_ref[alive].applied_emojis == frozenset({"git-merged"})
        assert by_ref[dead].applied_emojis == frozenset()

    async def test_webhook_for_untracked_pr(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        merged_info = PRInfo(state="closed", merged=True, reviews=())
        source = FakePRSource(merged_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 999)

        assert len(reactions.added) == 0

    async def test_webhook_adds_approval_to_existing_emojis(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        repo.stored.append(
            TrackedPR(
                pr_url=_pr_url(),
                message_ref=_msg_ref(),
                applied_emojis=frozenset({"speech_balloon"}),
            )
        )
        approved_info = PRInfo(
            state="open",
            merged=False,
            reviews=(Review(user_login="alice", state=ReviewState.APPROVED),),
        )
        source = FakePRSource(approved_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1)

        assert len(reactions.added) == 1
        assert reactions.added[0][1] == "git-approved"

    async def test_webhook_skips_excluded_sender(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        scope_keys = ("slack/T1/C123",)
        repo.stored.append(
            TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref(), scope_keys=scope_keys)
        )
        await exclusions.add("slack/T1/C123", "Cursor")
        merged_info = PRInfo(state="closed", merged=True, reviews=())
        source = FakePRSource(merged_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1, sender="Cursor")

        assert len(reactions.added) == 0

    async def test_webhook_processes_non_excluded_sender(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        scope_keys = ("slack/T1/C123",)
        repo.stored.append(
            TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref(), scope_keys=scope_keys)
        )
        await exclusions.add("slack/T1/C123", "Cursor")
        merged_info = PRInfo(state="closed", merged=True, reviews=())
        source = FakePRSource(merged_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1, sender="alice")

        assert len(reactions.added) == 1

    async def test_webhook_exclusion_is_case_insensitive(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        scope_keys = ("slack/T1/C123",)
        repo.stored.append(
            TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref(), scope_keys=scope_keys)
        )
        await exclusions.add("slack/T1/C123", "cursor")
        merged_info = PRInfo(state="closed", merged=True, reviews=())
        source = FakePRSource(merged_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1, sender="Cursor")

        assert len(reactions.added) == 0

    async def test_webhook_skips_self_review_when_muted(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        scope_keys = ("slack/T1/C123", "slack/T1", "slack")
        repo.stored.append(
            TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref(), scope_keys=scope_keys)
        )
        await scope_settings.set("slack/T1", "mute_self_reviews", True)
        commented_info = PRInfo(
            state="open",
            merged=False,
            reviews=(Review(user_login="alice", state=ReviewState.COMMENTED),),
            author_login="alice",
        )
        source = FakePRSource(commented_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1, sender="alice")

        assert len(reactions.added) == 0

    async def test_webhook_reacts_to_self_review_when_not_muted(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        scope_keys = ("slack/T1/C123", "slack/T1", "slack")
        repo.stored.append(
            TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref(), scope_keys=scope_keys)
        )
        commented_info = PRInfo(
            state="open",
            merged=False,
            reviews=(Review(user_login="alice", state=ReviewState.COMMENTED),),
            author_login="alice",
        )
        source = FakePRSource(commented_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1, sender="alice")

        assert len(reactions.added) == 1
        assert reactions.added[0][1] == "speech_balloon"

    async def test_webhook_mute_does_not_affect_other_reviewer(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        scope_keys = ("slack/T1/C123", "slack/T1", "slack")
        repo.stored.append(
            TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref(), scope_keys=scope_keys)
        )
        await scope_settings.set("slack/T1", "mute_self_reviews", True)
        commented_info = PRInfo(
            state="open",
            merged=False,
            reviews=(Review(user_login="bob", state=ReviewState.COMMENTED),),
            author_login="alice",
        )
        source = FakePRSource(commented_info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1, sender="bob")

        assert len(reactions.added) == 1

    async def test_webhook_excludes_excluded_reviewer_from_status(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        # cursor[bot] commented earlier; alice now approves. Status should
        # be APPROVED (not driven by the excluded cursor[bot] comment).
        scope_keys = ("slack/T1/C123", "slack/T1", "slack")
        repo.stored.append(
            TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref(), scope_keys=scope_keys)
        )
        await exclusions.add("slack/T1", "cursor[bot]")
        info = PRInfo(
            state="open",
            merged=False,
            reviews=(
                Review(user_login="cursor[bot]", state=ReviewState.COMMENTED),
                Review(user_login="alice", state=ReviewState.APPROVED),
            ),
        )
        source = FakePRSource(info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1, sender="alice")

        assert len(reactions.added) == 1
        assert reactions.added[0][1] == "git-approved"

    async def test_webhook_self_review_muted_for_third_party_sender(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        # Author Bob commented earlier; mute_self_reviews is enabled.
        # A synchronize webhook fires with a different sender (Alice).
        # The author's COMMENTED review must not drive a `speech_balloon`
        # reaction just because the existing sender==author short-circuit
        # doesn't trigger.
        scope_keys = ("slack/T1/C123", "slack/T1", "slack")
        repo.stored.append(
            TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref(), scope_keys=scope_keys)
        )
        await scope_settings.set("slack/T1", "mute_self_reviews", True)
        info = PRInfo(
            state="open",
            merged=False,
            reviews=(Review(user_login="bob", state=ReviewState.COMMENTED),),
            author_login="bob",
        )
        source = FakePRSource(info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        await use_case.execute("o", "r", 1, sender="alice")

        assert len(reactions.added) == 0

    async def test_webhook_no_reaction_when_only_excluded_reviewer(
        self,
        reactions: FakeReactions,
        repo: FakePRRepository,
        resolver: FakeEmojiConfigResolver,
        exclusions: FakeUserExclusionRepo,
        scope_settings: FakeScopeSettingsRepo,
    ) -> None:
        # If the only review is from cursor[bot] and cursor[bot] is excluded,
        # status should resolve to OPEN — no reaction at all.
        scope_keys = ("slack/T1/C123", "slack/T1", "slack")
        repo.stored.append(
            TrackedPR(pr_url=_pr_url(), message_ref=_msg_ref(), scope_keys=scope_keys)
        )
        await exclusions.add("slack/T1", "cursor[bot]")
        info = PRInfo(
            state="open",
            merged=False,
            reviews=(Review(user_login="cursor[bot]", state=ReviewState.COMMENTED),),
        )
        source = FakePRSource(info)
        use_case = HandleGitHubWebhook(
            source, reactions, repo, resolver, exclusions, scope_settings
        )

        # Webhook from a different sender (e.g. PR opened/synchronized event)
        await use_case.execute("o", "r", 1, sender="alice")

        assert len(reactions.added) == 0
