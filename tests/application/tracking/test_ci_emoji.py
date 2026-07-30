import pytest

from prbot.application.tracking.ci_emoji import ci_emoji_to_add
from prbot.domain.emoji.value_objects import EmojiConfig
from prbot.domain.tracking.entities import TrackedPR
from prbot.domain.tracking.value_objects import MessageRef, PRInfo, PRUrl

CI_EMOJI = EmojiConfig().ci_failed


def _tracked(applied: frozenset[str] = frozenset()) -> TrackedPR:
    return TrackedPR(
        pr_url=PRUrl(owner="o", repo="r", number=1),
        message_ref=MessageRef(integration_id="slack", ref="C1:1.2"),
        applied_emojis=applied,
    )


def _pr_info(ci_failing: bool | None) -> PRInfo:
    return PRInfo(state="open", merged=False, reviews=(), ci_failing=ci_failing)


class TestCiEmojiToAdd:
    def test_returns_emoji_and_fallback_when_failing(self) -> None:
        result = ci_emoji_to_add(EmojiConfig(), _pr_info(True), _tracked())
        assert result == (CI_EMOJI, EmojiConfig.fallback_for_status("ci_failed"))

    @pytest.mark.parametrize("ci_failing", [False, None])
    def test_none_when_not_failing(self, ci_failing: bool | None) -> None:
        assert ci_emoji_to_add(EmojiConfig(), _pr_info(ci_failing), _tracked()) is None

    def test_none_when_already_applied(self) -> None:
        tracked = _tracked(applied=frozenset({CI_EMOJI}))
        assert ci_emoji_to_add(EmojiConfig(), _pr_info(True), tracked) is None

    def test_respects_custom_emoji_name(self) -> None:
        result = ci_emoji_to_add(EmojiConfig(ci_failed="ci-broke"), _pr_info(True), _tracked())
        assert result is not None
        assert result[0] == "ci-broke"
