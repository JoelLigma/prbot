from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class PRStatus(StrEnum):
    """Resolved status of a PR.

    Every status except ``CI_FAILED`` is a mutually-exclusive outcome of
    ``resolve_pr_status`` — one wins per evaluation. ``CI_FAILED`` comes from
    check-runs, not reviews, so it is applied *alongside* that winner rather
    than replacing it.
    """

    MERGED = "merged"
    CLOSED = "closed"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    COMMENTED = "commented"
    OPEN = "open"
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


class CheckRun(BaseModel, frozen=True):
    """A single CI check-run on a commit, as reported by GitHub.

    Generic status data only — deciding what counts as "failing" is a policy
    concern left to the caller (see ``resolve_ci_failing``).
    """

    status: str  # "queued" | "in_progress" | "completed"
    conclusion: str | None  # "success" | "failure" | ...; None while running


class PRInfo(BaseModel, frozen=True):
    """Data fetched from GitHub API about a PR's current state."""

    state: str  # "open" or "closed"
    merged: bool
    reviews: tuple[Review, ...]
    author_login: str = ""
    ci_failing: bool | None = None
