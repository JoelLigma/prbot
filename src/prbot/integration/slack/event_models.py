from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SlackMessageBody(BaseModel):
    """Inner ``message`` object on a ``message_changed`` event.

    Attachments stay as raw dicts: their shape varies wildly across unfurl
    sources (Slack messages, Linear tickets, GitHub previews, etc.) and we
    intentionally scan all string fields rather than a fixed subset.
    """

    model_config = ConfigDict(extra="ignore")

    text: str = ""
    ts: str = ""
    team: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class SlackMessageEvent(BaseModel):
    """The subset of a Slack ``message`` event we care about for PR detection."""

    model_config = ConfigDict(extra="ignore")

    channel: str = ""
    subtype: str | None = None
    text: str = ""
    ts: str = ""
    team: str = ""
    message: SlackMessageBody | None = None
