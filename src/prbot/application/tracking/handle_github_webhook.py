import logging

from prbot.application.exclusions.manage_self_reviews import MUTE_SELF_REVIEWS_KEY
from prbot.domain.common.ports import ScopeSettingsPort
from prbot.domain.emoji.ports import EmojiConfigResolverPort
from prbot.domain.emoji.value_objects import EmojiConfig
from prbot.domain.exclusions.ports import UserExclusionPort
from prbot.domain.tracking.ports import PRRepositoryPort, PRSourcePort, ReactionPort
from prbot.domain.tracking.status_resolver import filter_pr_info, resolve_pr_status
from prbot.domain.tracking.value_objects import PRStatus, PRUrl

logger = logging.getLogger(__name__)


class HandleGitHubWebhook:
    """Use case: a source webhook fires, update all tracked messages."""

    def __init__(
        self,
        source: PRSourcePort,
        reactions: ReactionPort,
        pr_repository: PRRepositoryPort,
        emoji_resolver: EmojiConfigResolverPort,
        user_exclusions: UserExclusionPort,
        scope_settings: ScopeSettingsPort,
    ) -> None:
        self._source = source
        self._reactions = reactions
        self._repo = pr_repository
        self._emoji_resolver = emoji_resolver
        self._user_exclusions = user_exclusions
        self._scope_settings = scope_settings

    async def execute(
        self,
        owner: str,
        repo: str,
        number: int,
        sender: str | None = None,
    ) -> None:
        """Re-evaluate PR status and add new reactions to all messages tracking it."""
        pr_url = PRUrl(owner=owner, repo=repo, number=number)

        tracked_prs = await self._repo.find_by_pr_url(pr_url)
        if not tracked_prs:
            logger.debug("No tracked messages for %s", pr_url)
            return

        try:
            pr_info = await self._source.fetch_pr_info(pr_url)
        except Exception:
            logger.warning("Failed to fetch PR info for %s, skipping", pr_url)
            return

        # Cache per scope-chain to avoid repeated DB queries for identical scopes
        config_cache: dict[tuple[str, ...], EmojiConfig] = {}
        status_cache: dict[tuple[str, ...], PRStatus] = {}

        for tracked in tracked_prs:
            if sender:
                excluded = await self._user_exclusions.is_excluded(list(tracked.scope_keys), sender)
                if excluded:
                    logger.info(
                        "Skipping %s for %s — sender %r is excluded",
                        pr_url,
                        tracked.message_ref,
                        sender,
                    )
                    continue

            cache_key = tracked.scope_keys
            if cache_key not in status_cache:
                excluded_logins = await self._user_exclusions.excluded_logins(list(cache_key))
                mute = bool(await self._scope_settings.get(list(cache_key), MUTE_SELF_REVIEWS_KEY))
                status_cache[cache_key] = resolve_pr_status(
                    filter_pr_info(
                        pr_info,
                        excluded_logins=excluded_logins,
                        mute_self_review_comments=mute,
                    )
                )
            status = status_cache[cache_key]

            if cache_key not in config_cache:
                config_cache[cache_key] = await self._emoji_resolver.resolve(
                    list(tracked.scope_keys)
                )
            emoji = config_cache[cache_key].for_status(status)
            fallback = EmojiConfig.fallback_for_status(status)

            if emoji is None or tracked.has_emoji(emoji):
                continue

            await self._reactions.add_reaction(tracked.message_ref, emoji, fallback)
            await self._repo.add_emoji(pr_url, tracked.message_ref, emoji)
