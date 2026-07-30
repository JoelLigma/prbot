import logging
import re
import time
from datetime import datetime

import httpx
import jwt

from prbot.domain.exclusions.ports import GitHubUserKind, GitHubUserRef
from prbot.domain.tracking.status_resolver import resolve_ci_failing
from prbot.domain.tracking.value_objects import CheckRun, PRInfo, PRUrl, Review, ReviewState

_BOT_SUFFIX = "[bot]"
_USER_TYPE_TO_KIND: dict[str, GitHubUserKind] = {
    "User": "user",
    "Bot": "bot",
    "Organization": "organization",
}

_GITHUB_PR_PATTERN = re.compile(r"github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)")

logger = logging.getLogger(__name__)


class GitHubGateway:
    """Fetches PR data from GitHub REST API using GitHub App installation tokens."""

    def __init__(self, app_id: str, private_key: str) -> None:
        self._app_id = app_id
        self._private_key = private_key
        self._client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10.0,
        )
        # Cache: installation_id -> (token, expires_at)
        self._token_cache: dict[int, tuple[str, float]] = {}
        # Cache: owner -> installation_id
        self._installation_cache: dict[str, int] = {}

    def _generate_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (10 * 60),
            "iss": self._app_id,
        }
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    async def _get_installation_id(self, owner: str) -> int:
        if owner in self._installation_cache:
            return self._installation_cache[owner]

        token = self._generate_jwt()
        resp = await self._client.get(
            f"/orgs/{owner}/installation",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 404:
            # Try as a user installation
            resp = await self._client.get(
                f"/users/{owner}/installation",
                headers={"Authorization": f"Bearer {token}"},
            )
        resp.raise_for_status()
        installation_id: int = resp.json()["id"]
        self._installation_cache[owner] = installation_id
        return installation_id

    async def _get_token(self, owner: str) -> str:
        installation_id = await self._get_installation_id(owner)

        cached = self._token_cache.get(installation_id)
        if cached and cached[1] > time.time() + 60:
            return cached[0]

        jwt_token = self._generate_jwt()
        resp = await self._client.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        token: str = data["token"]
        expires_at = datetime.fromisoformat(data["expires_at"]).timestamp()
        self._token_cache[installation_id] = (token, expires_at)
        logger.info("Obtained installation token for %s (installation %d)", owner, installation_id)
        return token

    def extract_pr_references(self, text: str) -> list[PRUrl]:
        """Extract all GitHub PR URLs from the given text."""
        seen: set[tuple[str, str, int]] = set()
        results: list[PRUrl] = []
        for match in _GITHUB_PR_PATTERN.finditer(text):
            key = (match.group(1), match.group(2), int(match.group(3)))
            if key not in seen:
                seen.add(key)
                results.append(PRUrl(owner=key[0], repo=key[1], number=key[2]))
        return results

    async def fetch_pr_info(self, pr_url: PRUrl) -> PRInfo:
        token = await self._get_token(pr_url.owner)
        headers = {"Authorization": f"Bearer {token}"}

        pr_resp = await self._client.get(
            f"/repos/{pr_url.owner}/{pr_url.repo}/pulls/{pr_url.number}",
            headers=headers,
        )
        pr_resp.raise_for_status()
        pr_data = pr_resp.json()

        reviews: list[Review] = []
        page = 1
        while True:
            rev_resp = await self._client.get(
                f"/repos/{pr_url.owner}/{pr_url.repo}/pulls/{pr_url.number}/reviews",
                params={"per_page": 100, "page": page},
                headers=headers,
            )
            rev_resp.raise_for_status()
            page_data = rev_resp.json()
            if not page_data:
                break
            for r in page_data:
                reviews.append(
                    Review(
                        user_login=r["user"]["login"],
                        state=ReviewState(r["state"]),
                    )
                )
            if len(page_data) < 100:
                break
            page += 1

        head_sha = pr_data.get("head", {}).get("sha")
        check_runs = await self._fetch_check_runs(pr_url, head_sha, headers)

        return PRInfo(
            state=pr_data["state"],
            merged=pr_data.get("merged", False),
            reviews=tuple(reviews),
            author_login=pr_data.get("user", {}).get("login", ""),
            ci_failing=resolve_ci_failing(check_runs),
        )

    async def _fetch_check_runs(
        self,
        pr_url: PRUrl,
        head_sha: str | None,
        headers: dict[str, str],
    ) -> tuple[CheckRun, ...]:
        """Fetch all check-runs for a commit.

        Generic status data only — interpreting what counts as "failing" is the
        caller's concern (see ``resolve_ci_failing``). Returns an empty tuple when
        there is no head SHA or the request fails (e.g. the App lacks the
        *Checks: read* permission); callers treat "no data" as indeterminate.
        """
        if not head_sha:
            return ()

        try:
            runs: list[CheckRun] = []
            page = 1
            while True:
                resp = await self._client.get(
                    f"/repos/{pr_url.owner}/{pr_url.repo}/commits/{head_sha}/check-runs",
                    params={"per_page": 100, "page": page},
                    headers=headers,
                )
                resp.raise_for_status()
                page_runs = resp.json().get("check_runs", [])
                runs.extend(
                    CheckRun(status=r.get("status", ""), conclusion=r.get("conclusion"))
                    for r in page_runs
                )
                if len(page_runs) < 100:
                    break
                page += 1
        except Exception:
            logger.warning("Failed to fetch check-runs for %s@%s", pr_url, head_sha[:7])
            return ()

        return tuple(runs)

    async def lookup_user(self, github_username: str) -> GitHubUserRef | None:
        """Resolve a GitHub login via the public API."""
        stripped = github_username.strip()
        if stripped.lower().endswith(_BOT_SUFFIX):
            return await self.lookup_app(stripped[: -len(_BOT_SUFFIX)])
        if not stripped:
            return None

        resp = await self._client.get(f"/users/{stripped}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        kind = _USER_TYPE_TO_KIND.get(data.get("type", ""))
        if kind is None:
            return None
        return GitHubUserRef(login=data["login"], kind=kind)

    async def lookup_app(self, github_app_name: str) -> GitHubUserRef | None:
        """Resolve a GitHub bot via the public apps API."""
        # /apps/{slug} is public and rejects app JWTs scoped to a different app.
        resp = await self._client.get(f"/apps/{github_app_name}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return GitHubUserRef(login=github_app_name, kind="bot")

    async def close(self) -> None:
        await self._client.aclose()
