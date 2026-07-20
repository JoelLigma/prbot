from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class PRStatus(StrEnum):
    """Resolved status of a PR, ordered by priority."""

    MERGED = "merged"
    CLOSED = "closed"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    COMMENTED = "commented"
    OPEN = "open"
    # The statuses above are mutually-exclusive outcomes of resolve_pr_status()'s
    # priority chain — one wins per evaluation. CI failure is derived from
    # check-runs rather than reviews, so it is resolved on its own track in
    # HandleGitHubWebhook: a single webhook can add this emoji *and* a review
    # status emoji.
    CI_FAILED = "ci_failed"


class ReviewState(StrEnum):
    """GitHub review states as returned by the API."""

    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    COMMENTED = "COMMENTED"
    PENDING = "PENDING"
    DISMISSED = "DISMISSED"


class MessageRef(BaseModel, frozen=True):
    """Opaque reference to a message in an external messaging platform.

    The integration_id identifies which integration (e.g. "slack", "discord").
    The ref is integration-specific (e.g. "C123:1234567890.123" for Slack).
    """

    integration_id: str
    ref: str


class PRUrl(BaseModel, frozen=True):
    """Source-agnostic reference to a pull/merge request."""

    owner: str
    repo: str
    number: int

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


class Review(BaseModel, frozen=True):
    """A single review on a PR."""

    user_login: str
    state: ReviewState


class PRInfo(BaseModel, frozen=True):
    """Data fetched from GitHub API about a PR's current state."""

    state: str  # "open" or "closed"
    merged: bool
    reviews: tuple[Review, ...]
    author_login: str = ""
    ci_failing: bool | None = None
