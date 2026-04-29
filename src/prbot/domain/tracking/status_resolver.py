from prbot.domain.tracking.value_objects import PRInfo, PRStatus, ReviewState


def filter_pr_info(
    pr_info: PRInfo,
    *,
    excluded_logins: set[str] | None = None,
    mute_self_review_comments: bool = False,
) -> PRInfo:
    """Drop reviews that should not influence status resolution for a scope.

    - ``excluded_logins``: lowercased set of logins to ignore entirely.
    - ``mute_self_review_comments``: if True, COMMENTED reviews authored by the
      PR author are dropped (mirrors the per-scope ``mute_self_reviews`` flag).
    """
    reviews = pr_info.reviews
    if mute_self_review_comments and pr_info.author_login:
        author = pr_info.author_login.lower()
        reviews = tuple(
            r
            for r in reviews
            if not (r.user_login.lower() == author and r.state == ReviewState.COMMENTED)
        )
    if excluded_logins:
        reviews = tuple(r for r in reviews if r.user_login.lower() not in excluded_logins)
    if reviews is pr_info.reviews:
        return pr_info
    return pr_info.model_copy(update={"reviews": reviews})


def resolve_pr_status(pr_info: PRInfo) -> PRStatus:
    """Determine the PR status based on state and reviews.

    Priority order:
    1. merged → MERGED
    2. closed (not merged) → CLOSED
    3. changes_requested (latest review from any reviewer) → CHANGES_REQUESTED
    4. approved (latest reviews, no outstanding changes_requested) → APPROVED
    5. commented (review exists but not approved/changes_requested) → COMMENTED
    6. open (no reviews yet) → OPEN
    """
    if pr_info.merged:
        return PRStatus.MERGED

    if pr_info.state == "closed":
        return PRStatus.CLOSED

    # PR is open — examine reviews.
    # Build map of latest review per reviewer, skipping DISMISSED and PENDING.
    latest_reviews: dict[str, ReviewState] = {}
    for review in pr_info.reviews:
        if review.state == ReviewState.PENDING:
            continue
        if review.state == ReviewState.DISMISSED:
            latest_reviews.pop(review.user_login, None)
            continue
        latest_reviews[review.user_login] = review.state

    if not latest_reviews:
        return PRStatus.OPEN

    review_states = set(latest_reviews.values())

    if ReviewState.CHANGES_REQUESTED in review_states:
        return PRStatus.CHANGES_REQUESTED

    if ReviewState.APPROVED in review_states:
        return PRStatus.APPROVED

    if ReviewState.COMMENTED in review_states:
        return PRStatus.COMMENTED

    return PRStatus.OPEN
