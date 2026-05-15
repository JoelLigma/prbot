from prbot.integration.slack.handler import (
    build_scope_keys,
    parse_message_event,
)


class TestBuildScopeKeys:
    def test_full_scope(self) -> None:
        keys = build_scope_keys(team="T1", channel="C1")
        assert keys == ["slack/T1/C1", "slack/T1", "slack"]

    def test_team_only(self) -> None:
        keys = build_scope_keys(team="T1", channel="")
        assert keys == ["slack/T1", "slack"]

    def test_no_team_no_channel(self) -> None:
        keys = build_scope_keys(team="", channel="")
        assert keys == ["slack"]


class TestParseMessageEventPlain:
    def test_extracts_fields_and_advances_cursor(self) -> None:
        parsed = parse_message_event(
            {
                "text": "see https://github.com/o/r/pull/1",
                "channel": "C1",
                "ts": "1.0",
                "team": "T1",
            }
        )

        assert parsed is not None
        assert parsed.channel == "C1"
        assert parsed.ts == "1.0"
        assert parsed.text == "see https://github.com/o/r/pull/1"
        assert parsed.team == "T1"
        assert parsed.advance_cursor is True

    def test_returns_none_without_channel(self) -> None:
        parsed = parse_message_event({"text": "x", "ts": "1.0"})
        assert parsed is None

    def test_returns_none_without_ts(self) -> None:
        parsed = parse_message_event({"text": "x", "channel": "C1"})
        assert parsed is None


class TestParseMessageEventChanged:
    def test_uses_inner_message_and_skips_cursor(self) -> None:
        parsed = parse_message_event(
            {
                "subtype": "message_changed",
                "channel": "C1",
                "ts": "2.0",
                "message": {
                    "text": "shared",
                    "ts": "1.0",
                    "team": "T1",
                    "attachments": [{"text": "see https://github.com/o/r/pull/42"}],
                },
            }
        )

        assert parsed is not None
        assert parsed.channel == "C1"
        assert parsed.ts == "1.0"
        assert "github.com/o/r/pull/42" in parsed.text
        assert "shared" in parsed.text
        assert parsed.team == "T1"
        assert parsed.advance_cursor is False

    def test_falls_back_to_outer_team(self) -> None:
        parsed = parse_message_event(
            {
                "subtype": "message_changed",
                "channel": "C1",
                "team": "T_outer",
                "message": {"text": "x", "ts": "1.0"},
            }
        )

        assert parsed is not None
        assert parsed.team == "T_outer"

    def test_returns_none_when_message_missing(self) -> None:
        parsed = parse_message_event({"subtype": "message_changed", "channel": "C1", "ts": "2.0"})
        assert parsed is None

    def test_pulls_pr_url_from_attachment_only(self) -> None:
        parsed = parse_message_event(
            {
                "subtype": "message_changed",
                "channel": "C1",
                "message": {
                    "text": "",
                    "ts": "1.0",
                    "attachments": [
                        {
                            "is_msg_unfurl": True,
                            "from_url": "https://x.slack.com/archives/C/p1",
                            "text": "look at https://github.com/o/r/pull/9",
                        }
                    ],
                },
            }
        )

        assert parsed is not None
        assert "github.com/o/r/pull/9" in parsed.text


class TestParseMessageEventOtherSubtypes:
    def test_message_deleted_has_no_text_so_no_processing(self) -> None:
        parsed = parse_message_event({"subtype": "message_deleted", "channel": "C1", "ts": "1.0"})
        # Falls through to default path but text is empty — caller still gets
        # a parsed event so the cursor can advance.
        assert parsed is not None
        assert parsed.text == ""
        assert parsed.advance_cursor is True

    def test_bot_message_is_processed_like_normal_message(self) -> None:
        parsed = parse_message_event(
            {
                "subtype": "bot_message",
                "channel": "C1",
                "ts": "1.0",
                "text": "see https://github.com/o/r/pull/1",
            }
        )
        assert parsed is not None
        assert "github.com/o/r/pull/1" in parsed.text
