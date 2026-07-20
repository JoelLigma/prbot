from pydantic import BaseModel

_UNICODE_FALLBACKS: dict[str, str] = {
    "merged": "\N{TWISTED RIGHTWARDS ARROWS}",
    "closed": "\N{HEADSTONE}",
    "changes_requested": "\N{NO ENTRY SIGN}",
    "approved": "\N{WHITE HEAVY CHECK MARK}",
    "commented": "\N{SPEECH BALLOON}",
    "ci_failed": "\N{CROSS MARK}",
}


class EmojiConfig(BaseModel):
    """Configurable emoji names for each PR status."""

    merged: str = "git-merged"
    closed: str = "headstone"
    changes_requested: str = "git-changes-requested"
    approved: str = "git-approved"
    commented: str = "speech_balloon"
    ci_failed: str = "ci_failed"

    def for_status(self, status: str) -> str | None:
        """Return the emoji name for a PR status, or None for statuses with no reaction."""
        mapping: dict[str, str] = {
            "merged": self.merged,
            "closed": self.closed,
            "changes_requested": self.changes_requested,
            "approved": self.approved,
            "commented": self.commented,
            "ci_failed": self.ci_failed,
        }
        return mapping.get(status)

    @staticmethod
    def fallback_for_status(status: str) -> str | None:
        """Return a guaranteed-unicode emoji for a status, usable as a platform fallback.

        Used when the configured emoji (which may be a custom guild-specific name)
        doesn't exist on the target platform. The unicode equivalents always resolve.
        """
        return _UNICODE_FALLBACKS.get(status)
