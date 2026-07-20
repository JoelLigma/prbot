from prbot.domain.emoji.value_objects import EmojiConfig


class TestEmojiConfig:
    def test_default_mapping(self) -> None:
        config = EmojiConfig()
        assert config.for_status("merged") == "git-merged"
        assert config.for_status("closed") == "headstone"
        assert config.for_status("changes_requested") == "git-changes-requested"
        assert config.for_status("approved") == "git-approved"
        assert config.for_status("commented") == "speech_balloon"
        assert config.for_status("ci_failed") == "ci_failed"

    def test_ci_failed_default_primary_with_unicode_fallback(self) -> None:
        # Primary is the custom emoji name `ci_failed`; the fallback is the
        # native ❌ literal, which the Slack adapter aliases to :x: and Discord
        # uses as the literal — so it resolves without any upload.
        config = EmojiConfig()
        assert config.ci_failed == "ci_failed"
        assert EmojiConfig.fallback_for_status("ci_failed") == "\N{CROSS MARK}"

    def test_custom_ci_failed_emoji(self) -> None:
        config = EmojiConfig(ci_failed="ci-broke")
        assert config.for_status("ci_failed") == "ci-broke"

    def test_open_returns_none(self) -> None:
        config = EmojiConfig()
        assert config.for_status("open") is None

    def test_custom_emoji(self) -> None:
        config = EmojiConfig(merged="rocket", approved="shipit")
        assert config.for_status("merged") == "rocket"
        assert config.for_status("approved") == "shipit"
        assert config.for_status("closed") == "headstone"  # unchanged default

    def test_fallback_returns_unicode_for_known_statuses(self) -> None:
        statuses = ("merged", "closed", "changes_requested", "approved", "commented", "ci_failed")
        for status in statuses:
            fallback = EmojiConfig.fallback_for_status(status)
            assert fallback is not None
            assert not fallback.isascii(), f"fallback for {status} should be unicode"

    def test_fallback_returns_none_for_unknown_status(self) -> None:
        assert EmojiConfig.fallback_for_status("open") is None
