import logging
from collections.abc import Sequence

from prbot.application.exclusions.manage_self_reviews import MUTE_SELF_REVIEWS_KEY
from prbot.domain.common.ports import ScopeSettingsPort
from prbot.domain.emoji.ports import EmojiConfigResolverPort
from prbot.domain.exclusions.ports import UserExclusionPort
from prbot.domain.tracking.entities import TrackedPR
from prbot.domain.tracking.ports import PRRepositoryPort, PRSourcePort, ReactionPort
from prbot.domain.tracking.status_resolver import filter_pr_info, resolve_pr_status
from prbot.domain.tracking.value_objects import MessageRef

logger = logging.getLogger(__name__)


class HandleIncomingMessage:
    """Use case: a new message arrives from a messaging platform, check for PR URLs."""

    def __init__(
        self,
        sources: Sequence[PRSourcePort],
        reactions: ReactionPort,
        pr_repository: PRRepositoryPort,
        emoji_resolver: EmojiConfigResolverPort,
        user_exclusions: UserExclusionPort,
        scope_settings: ScopeSettingsPort,
    ) -> None:
        self._sources = sources
        self._reactions = reactions
        self._repo = pr_repository
        self._emoji_resolver = emoji_resolver
        self._user_exclusions = user_exclusions
        self._scope_settings = scope_settings

    async def execute(
        self,
        message_ref: MessageRef,
        text: str,
        scope_keys: list[str] | None = None,
    ) -> None:
        """Process a message, find PR URLs via all registered sources, fetch status, react."""
        resolved_keys = tuple(scope_keys or [])
        emoji_config = await self._emoji_resolver.resolve(list(resolved_keys))
        excluded_logins = await self._user_exclusions.excluded_logins(list(resolved_keys))
        mute = bool(await self._scope_settings.get(list(resolved_keys), MUTE_SELF_REVIEWS_KEY))

        for source in self._sources:
            pr_urls = source.extract_pr_references(text)

            for pr_url in pr_urls:
                try:
                    pr_info = await source.fetch_pr_info(pr_url)
                except Exception:
                    logger.warning("Failed to fetch PR info for %s, skipping", pr_url)
                    continue

                status = resolve_pr_status(
                    filter_pr_info(
                        pr_info,
                        excluded_logins=excluded_logins,
                        mute_self_review_comments=mute,
                    )
                )
                emoji = emoji_config.for_status(status)
                fallback = emoji_config.fallback_for_status(status)

                tracked = TrackedPR(
                    pr_url=pr_url,
                    message_ref=message_ref,
                    scope_keys=resolved_keys,
                )

                if emoji is not None:
                    await self._reactions.add_reaction(message_ref, emoji, fallback)
                    tracked = tracked.with_added_emoji(emoji)

                await self._repo.save(tracked)
