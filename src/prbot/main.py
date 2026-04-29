import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from prbot.application.commands import build_default_dispatcher
from prbot.application.exclusions.manage_self_reviews import ManageSelfReviews
from prbot.application.exclusions.manage_user_exclusions import ManageUserExclusions
from prbot.application.tracking.backfill_missed_messages import BackfillMissedMessages
from prbot.application.tracking.handle_github_webhook import HandleGitHubWebhook
from prbot.application.tracking.handle_incoming_message import HandleIncomingMessage
from prbot.application.tracking.reconcile_tracked_prs import ReconcileTrackedPRs
from prbot.config import Settings
from prbot.data.database import (
    database_url_from_path,
    make_engine,
    make_session_factory,
    run_migrations,
)
from prbot.data.repository import SQLiteChannelCursorRepository, SQLitePRRepository
from prbot.data.scope_config import ScopeConfigEmojiResolver
from prbot.data.scope_settings import SQLiteScopeSettingsRepository
from prbot.data.user_exclusions import SQLiteUserExclusionRepository
from prbot.infrastructure.github_gateway import GitHubGateway
from prbot.infrastructure.github_webhook_models import (
    PullRequestEvent,
    PullRequestReviewEvent,
)
from prbot.infrastructure.webhook_verification import verify_github_signature
from prbot.integration import IntegrationRegistry
from prbot.integration.discord.gateway import INTEGRATION_ID as DISCORD_INTEGRATION_ID
from prbot.integration.discord.gateway import encode_ref as discord_encode_ref
from prbot.integration.discord.gateway import seed_cursor as discord_seed_cursor
from prbot.integration.discord.handler import DiscordIntegration
from prbot.integration.discord.handler import build_scope_keys as discord_build_scope_keys
from prbot.integration.slack.gateway import INTEGRATION_ID as SLACK_INTEGRATION_ID
from prbot.integration.slack.gateway import encode_ref
from prbot.integration.slack.gateway import seed_cursor as slack_seed_cursor
from prbot.integration.slack.handler import SlackIntegration, build_scope_keys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = Settings()  # type: ignore[call-arg]

# --- Infrastructure ---
github_gateway = GitHubGateway(
    app_id=settings.github_app_id,
    private_key=settings.github_private_key,
)
database_url = database_url_from_path(settings.database_path)
engine = make_engine(database_url)
session_factory = make_session_factory(engine)
pr_repository = SQLitePRRepository(session_factory=session_factory)
cursor_repository = SQLiteChannelCursorRepository(session_factory=session_factory)
scope_settings_repo = SQLiteScopeSettingsRepository(session_factory=session_factory)
emoji_resolver = ScopeConfigEmojiResolver(
    settings=scope_settings_repo,
    default=settings.emoji,
)
user_exclusion_repo = SQLiteUserExclusionRepository(settings=scope_settings_repo)

# --- Integration Registry ---
registry = IntegrationRegistry()

# --- Use Cases ---
handle_incoming_message = HandleIncomingMessage(
    sources=[github_gateway],
    reactions=registry,
    pr_repository=pr_repository,
    emoji_resolver=emoji_resolver,
    user_exclusions=user_exclusion_repo,
    scope_settings=scope_settings_repo,
)
handle_github_webhook = HandleGitHubWebhook(
    source=github_gateway,
    reactions=registry,
    pr_repository=pr_repository,
    emoji_resolver=emoji_resolver,
    user_exclusions=user_exclusion_repo,
    scope_settings=scope_settings_repo,
)
reconcile_tracked_prs = ReconcileTrackedPRs(
    pr_repository=pr_repository,
    handle_webhook=handle_github_webhook,
)
manage_user_exclusions = ManageUserExclusions(
    exclusion_repo=user_exclusion_repo,
    github_lookup=github_gateway,
)
manage_self_reviews = ManageSelfReviews(settings=scope_settings_repo)
command_dispatcher = build_default_dispatcher(
    manage_user_exclusions, manage_self_reviews, emoji_resolver
)

# --- Register Integrations ---
if settings.slack is not None:
    backfill_missed_messages = BackfillMissedMessages(
        integration_id=SLACK_INTEGRATION_ID,
        cursor_repo=cursor_repository,
        handle_incoming_message=handle_incoming_message,
        build_message_ref=encode_ref,
        build_scope_keys=build_scope_keys,
        seed_cursor=slack_seed_cursor,
    )
    slack_integration = SlackIntegration(
        config=settings.slack,
        handle_incoming_message=handle_incoming_message,
        cursor_repo=cursor_repository,
        backfill=backfill_missed_messages,
        command_dispatcher=command_dispatcher,
    )
    registry.register(slack_integration)

if settings.discord is not None:
    discord_backfill = BackfillMissedMessages(
        integration_id=DISCORD_INTEGRATION_ID,
        cursor_repo=cursor_repository,
        handle_incoming_message=handle_incoming_message,
        build_message_ref=discord_encode_ref,
        build_scope_keys=discord_build_scope_keys,
        seed_cursor=discord_seed_cursor,
    )
    discord_integration = DiscordIntegration(
        config=settings.discord,
        handle_incoming_message=handle_incoming_message,
        cursor_repo=cursor_repository,
        backfill=discord_backfill,
        command_dispatcher=command_dispatcher,
    )
    registry.register(discord_integration)


# --- FastAPI Lifespan ---
def _log_reconciliation_result(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        logger.info("Reconciliation task was cancelled")
    elif exc := task.exception():
        logger.error("Reconciliation task failed unexpectedly: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    run_migrations(database_url)
    logger.info("Database migrations applied")
    await registry.start_all()
    reconciliation_task = asyncio.create_task(
        reconcile_tracked_prs.execute(),
        name="startup-reconciliation",
    )
    reconciliation_task.add_done_callback(_log_reconciliation_result)
    yield
    if not reconciliation_task.done():
        reconciliation_task.cancel()
        try:
            await reconciliation_task
        except asyncio.CancelledError:
            logger.info("Reconciliation cancelled during shutdown")
    await registry.stop_all()
    await engine.dispose()
    await github_gateway.close()
    logger.info("Shutdown complete")


# --- FastAPI App ---
api = FastAPI(lifespan=lifespan)
registry.register_all_routes(api)


@api.post("/github/webhooks")
async def github_webhooks(req: Request) -> dict[str, bool]:
    """GitHub webhook endpoint with HMAC-SHA256 verification."""
    body = await req.body()
    signature = req.headers.get("X-Hub-Signature-256")

    if not verify_github_signature(body, settings.github_webhook_secret, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    event_type = req.headers.get("X-GitHub-Event")

    if event_type not in ("pull_request", "pull_request_review"):
        logger.warning("Ignoring GitHub event: %s", event_type)
        return {"ok": True}

    logger.info("Received GitHub event: %s", event_type)

    if not body:
        logger.warning("Empty body for %s event, skipping", event_type)
        return {"ok": True}

    payload = await req.json()

    if event_type == "pull_request":
        event = PullRequestEvent.model_validate(payload)
        logger.info(
            "PR event: %s %s#%d",
            event.action,
            event.repository.full_name,
            event.pull_request.number,
        )
        if event.action in ("opened", "closed", "reopened", "synchronize"):
            owner, repo = event.repository.full_name.split("/")
            await handle_github_webhook.execute(
                owner=owner,
                repo=repo,
                number=event.pull_request.number,
                sender=event.sender.login,
            )

    elif event_type == "pull_request_review":
        review_event = PullRequestReviewEvent.model_validate(payload)
        logger.info(
            "PR review event: %s %s#%d",
            review_event.action,
            review_event.repository.full_name,
            review_event.pull_request.number,
        )
        if review_event.action in ("submitted", "dismissed"):
            owner, repo = review_event.repository.full_name.split("/")
            await handle_github_webhook.execute(
                owner=owner,
                repo=repo,
                number=review_event.pull_request.number,
                sender=review_event.sender.login,
            )

    return {"ok": True}


@api.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
