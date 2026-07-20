from pydantic import BaseModel


class WebhookRepository(BaseModel):
    full_name: str  # "owner/repo"


class WebhookPullRequest(BaseModel):
    number: int
    state: str  # "open" or "closed"
    merged: bool = False


class WebhookReview(BaseModel):
    state: str  # "approved", "changes_requested", "commented", "dismissed"


class WebhookUser(BaseModel):
    login: str


class PullRequestEvent(BaseModel):
    action: str  # "opened", "closed", "reopened", "synchronize"
    pull_request: WebhookPullRequest
    repository: WebhookRepository
    sender: WebhookUser


class PullRequestReviewEvent(BaseModel):
    action: str  # "submitted", "dismissed"
    review: WebhookReview
    pull_request: WebhookPullRequest
    repository: WebhookRepository
    sender: WebhookUser


class WebhookCheckSuitePullRequest(BaseModel):
    number: int


class WebhookCheckSuite(BaseModel):
    # PRs are only populated for same-repo branches; empty for forked-PR runs.
    pull_requests: list[WebhookCheckSuitePullRequest] = []


class CheckSuiteEvent(BaseModel):
    action: str  # "completed", "requested", "rerequested"
    check_suite: WebhookCheckSuite
    repository: WebhookRepository
    sender: WebhookUser
