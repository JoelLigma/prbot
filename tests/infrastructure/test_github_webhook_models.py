from prbot.infrastructure.github_webhook_models import CheckSuiteEvent


class TestCheckSuiteEvent:
    def test_parses_pull_request_numbers(self) -> None:
        event = CheckSuiteEvent.model_validate(
            {
                "action": "completed",
                "check_suite": {
                    "conclusion": "failure",
                    "pull_requests": [{"number": 7}, {"number": 8}],
                },
                "repository": {"full_name": "octocat/hello"},
                "sender": {"login": "ci-bot"},
            }
        )

        assert event.action == "completed"
        assert [pr.number for pr in event.check_suite.pull_requests] == [7, 8]
        assert event.repository.full_name == "octocat/hello"
        assert event.sender.login == "ci-bot"

    def test_empty_pull_requests_for_fork_runs(self) -> None:
        # Forked-PR check suites omit pull_requests — must parse to an empty list.
        event = CheckSuiteEvent.model_validate(
            {
                "action": "completed",
                "check_suite": {"conclusion": "failure", "pull_requests": []},
                "repository": {"full_name": "octocat/hello"},
                "sender": {"login": "ci-bot"},
            }
        )

        assert event.check_suite.pull_requests == []
