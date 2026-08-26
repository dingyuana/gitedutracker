import sys
import os
import pytest
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.services.github_service import (
    fetch_activity,
    GitHubError,
    GitHubNotFoundError,
    GitHubPermissionError,
    _normalize_repo,
    _date_to_utc_range,
)
from github import GithubException


@pytest.fixture
def mock_date():
    return date(2026, 8, 21)


@pytest.fixture
def sample_commit_list():
    return [
        {
            "sha": "abc123",
            "commit": {"message": "feat: add login page"},
            "stats": {"additions": 50, "deletions": 10, "total": 60},
            "files": [
                {"filename": "login.py", "additions": 30, "deletions": 5},
                {"filename": "test_login.py", "additions": 20, "deletions": 5},
            ],
        },
        {
            "sha": "def456",
            "commit": {"message": "fix: auth bug"},
            "stats": {"additions": 5, "deletions": 8, "total": 13},
            "files": [
                {"filename": "auth.py", "additions": 5, "deletions": 8},
            ],
        },
    ]


@pytest.fixture
def sample_pulls_list():
    return [
        {"number": 1, "state": "merged", "title": "Add feature"},
        {"number": 2, "state": "open", "title": "Fix bug"},
        {"number": 3, "state": "closed", "title": "WIP"},
    ]


class TestNormalizeRepo:

    def test_url_format(self):
        assert _normalize_repo("https://github.com/user/repo") == "user/repo"

    def test_url_format_with_git_suffix(self):
        assert _normalize_repo("https://github.com/user/repo.git") == "user/repo"

    def test_owner_repo_with_git_suffix(self):
        assert _normalize_repo("user/repo.git") == "user/repo"

    def test_url_format_with_trailing_slash(self):
        assert _normalize_repo("https://github.com/user/repo/") == "user/repo"

    def test_owner_repo_format(self):
        assert _normalize_repo("user/repo") == "user/repo"

    def test_empty_string(self):
        with pytest.raises(GitHubError):
            _normalize_repo("")


class TestDateToUtcRange:

    def test_returns_datetime_objects(self, mock_date):
        since, until = _date_to_utc_range(mock_date)
        assert isinstance(since, datetime)
        assert isinstance(until, datetime)

    def test_until_is_one_day_after_since(self, mock_date):
        since, until = _date_to_utc_range(mock_date)
        assert until - since == timedelta(days=1)

    def test_times_are_utc(self, mock_date):
        since, until = _date_to_utc_range(mock_date)
        assert since.tzinfo == timezone.utc
        assert until.tzinfo == timezone.utc

    def test_shanghai_midnight_becomes_utc_midnight_minus_8(self, mock_date):
        # Asia/Shanghai is UTC+8, so midnight CST = 16:00 previous day UTC
        since, until = _date_to_utc_range(mock_date)
        assert since.hour == 16
        assert since.day == 20
        assert since.month == 8

        assert until.hour == 16
        assert until.day == 21
        assert until.month == 8


class TestFetchActivitySuccess:

    @patch("app.services.github_service.Github")
    def test_returns_correct_structure(self, mock_github_cls, mock_date, sample_commit_list, sample_pulls_list):
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github

        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        # Commits
        mock_commit = MagicMock()
        mock_commit.sha = "abc123"
        mock_commit.commit.message = "feat: add login page"
        mock_commit.stats.additions = 50
        mock_commit.stats.deletions = 10
        mock_commit.files = [
            MagicMock(filename="login.py"),
            MagicMock(filename="test_login.py"),
        ]

        mock_commit2 = MagicMock()
        mock_commit2.sha = "def456"
        mock_commit2.commit.message = "fix: auth bug"
        mock_commit2.stats.additions = 5
        mock_commit2.stats.deletions = 8
        mock_commit2.files = [MagicMock(filename="auth.py")]

        mock_commits_page = [mock_commit, mock_commit2]
        mock_repo.get_commits.return_value = mock_commits_page

        # PRs
        mock_pr1 = MagicMock()
        mock_pr1.state = "merged"
        mock_pr2 = MagicMock()
        mock_pr2.state = "open"
        mock_pr3 = MagicMock()
        mock_pr3.state = "closed"
        mock_repo.get_pulls.return_value = [mock_pr1, mock_pr2, mock_pr3]

        result = fetch_activity("user/repo", mock_date, github_token="fake_token")

        assert result["commits_count"] == 2
        assert len(result["commits"]) == 2
        assert result["commits"][0]["sha"] == "abc123"
        assert result["commits"][0]["message"] == "feat: add login page"
        assert result["commits"][0]["additions"] == 50
        assert result["commits"][0]["deletions"] == 10
        assert result["commits"][0]["files"] == 2
        assert result["prs_opened"] == 1
        assert result["prs_merged"] == 1
        assert result["loc_additions"] == 55
        assert result["loc_deletions"] == 18

    @patch("app.services.github_service.Github")
    def test_url_normalization(self, mock_github_cls, mock_date):
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_commits.return_value = MagicMock()
        mock_repo.get_commits.return_value.get_page.return_value = []
        mock_repo.get_pulls.return_value = []

        fetch_activity("https://github.com/user/repo", mock_date, github_token="fake_token")
        mock_github.get_repo.assert_called_once_with("user/repo")

    @patch("app.services.github_service.Github")
    def test_empty_commits_and_prs(self, mock_github_cls, mock_date):
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_commits.return_value = MagicMock()
        mock_repo.get_commits.return_value.get_page.return_value = []
        mock_repo.get_pulls.return_value = []

        result = fetch_activity("user/repo", mock_date, github_token="fake_token")

        assert result["commits_count"] == 0
        assert result["commits"] == []
        assert result["prs_opened"] == 0
        assert result["prs_merged"] == 0
        assert result["loc_additions"] == 0
        assert result["loc_deletions"] == 0

    @patch("app.services.github_service.Github")
    def test_prs_counted_correctly(self, mock_github_cls, mock_date):
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_commits.return_value = MagicMock()
        mock_repo.get_commits.return_value.get_page.return_value = []
        mock_repo.get_pulls.return_value = [
            MagicMock(state="merged"),
            MagicMock(state="merged"),
            MagicMock(state="open"),
            MagicMock(state="closed"),
        ]

        result = fetch_activity("user/repo", mock_date, github_token="fake_token")

        assert result["prs_opened"] == 1
        assert result["prs_merged"] == 2


class TestFetchActivityErrors:

    @patch("app.services.github_service.Github")
    def test_not_found_raises_github_not_found_error(self, mock_github_cls, mock_date):
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_github.get_repo.side_effect = GithubException(404, {"message": "Not Found"})

        with pytest.raises(GitHubNotFoundError):
            fetch_activity("nonexistent/repo", mock_date, github_token="fake_token")

    @patch("app.services.github_service.Github")
    def test_permission_error_raises_github_permission_error(self, mock_github_cls, mock_date):
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_github.get_repo.side_effect = GithubException(403, {"message": "Forbidden"})

        with pytest.raises(GitHubPermissionError):
            fetch_activity("private/repo", mock_date, github_token="bad_token")

    @patch("app.services.github_service.Github")
    def test_commits_api_error_raises_not_found(self, mock_github_cls, mock_date):
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_commits.side_effect = GithubException(404, {"message": "Not Found"})

        with pytest.raises(GitHubNotFoundError):
            fetch_activity("user/repo", mock_date, github_token="fake_token")

    @patch("app.services.github_service.Github")
    def test_commits_api_error_raises_permission_error(self, mock_github_cls, mock_date):
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_commits.side_effect = GithubException(403, {"message": "Forbidden"})

        with pytest.raises(GitHubPermissionError):
            fetch_activity("private/repo", mock_date, github_token="bad_token")


class TestFetchActivityTimezone:

    @patch("app.services.github_service.Github")
    def test_since_until_passed_correctly(self, mock_github_cls, mock_date):
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_commits.return_value = MagicMock()
        mock_repo.get_commits.return_value.get_page.return_value = []
        mock_repo.get_pulls.return_value = []

        fetch_activity("user/repo", mock_date, github_token="fake_token")

        call_kwargs = mock_repo.get_commits.call_args[1]
        since = call_kwargs["since"]
        until = call_kwargs["until"]

        assert since == datetime(2026, 8, 20, 16, 0, tzinfo=timezone.utc)
        assert until == datetime(2026, 8, 21, 16, 0, tzinfo=timezone.utc)


class TestRobustness:

    @patch("app.services.github_service.Github")
    def test_commit_files_paginatedlist_no_len(self, mock_github_cls, mock_date):
        from unittest.mock import MagicMock
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo

        mock_commit = MagicMock()
        mock_commit.sha = "aaa"
        mock_commit.commit.message = "feat: x"
        mock_commit.stats.additions = 10
        mock_commit.stats.deletions = 2
        paginated_like = MagicMock()
        mock_commit.files = paginated_like

        mock_repo.get_commits.return_value = [mock_commit]
        mock_repo.get_pulls.return_value = []

        from app.services.github_service import fetch_activity
        result = fetch_activity("user/repo", mock_date, github_token="t")
        assert result["commits_count"] == 1
        assert result["commits"][0]["files"] == 0

    @patch("app.services.github_service.Github")
    def test_pull_fetch_failure_is_non_fatal(self, mock_github_cls, mock_date):
        from unittest.mock import MagicMock
        from github import GithubException
        mock_github = MagicMock()
        mock_github_cls.return_value = mock_github
        mock_repo = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_commit = MagicMock()
        mock_commit.sha = "bbb"
        mock_commit.commit.message = "m"
        mock_commit.stats.additions = 1
        mock_commit.stats.deletions = 1
        mock_commit.files = [MagicMock()]
        mock_repo.get_commits.return_value = [mock_commit]
        mock_repo.get_pulls.side_effect = GithubException(403, {"message": "rate limit"}, None)

        from app.services.github_service import fetch_activity
        result = fetch_activity("user/repo", mock_date, github_token="t")

        assert result["prs_opened"] == 0
        assert result["prs_merged"] == 0
        assert result["commits_count"] == 1
