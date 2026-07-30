from prbot.domain.emoji.value_objects import EmojiConfig
from prbot.domain.tracking.entities import TrackedPR
from prbot.domain.tracking.value_objects import PRInfo, PRStatus


def ci_emoji_to_add(
    config: EmojiConfig, pr_info: PRInfo, tracked: TrackedPR
) -> tuple[str, str | None] | None:
    """The (emoji, fallback) to add for a CI failure, or None if nothing to add."""
    if pr_info.ci_failing is not True:
        return None
    emoji = config.for_status(PRStatus.CI_FAILED)
    if emoji is None or tracked.has_emoji(emoji):
        return None
    return emoji, EmojiConfig.fallback_for_status(PRStatus.CI_FAILED)
