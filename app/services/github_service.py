from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from github import Github
from github import GithubException


class GitHubError(Exception):
    pass


class GitHubNotFoundError(GitHubError):
    pass


class GitHubPermissionError(GitHubError):
    pass


def _normalize_repo(repo: str) -> str:
    repo = repo.strip()
    if not repo:
        raise GitHubError("Empty repository name")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if repo.startswith("http"):
        parts = urlparse(repo).path.rstrip("/").split("/")
        if len(parts) < 2:
            raise GitHubError(f"Invalid GitHub URL: {repo}")
        return f"{parts[-2]}/{parts[-1]}"
    return repo


def _date_to_utc_range(d: date) -> tuple[datetime, datetime]:
    tz = ZoneInfo("Asia/Shanghai")
    start = datetime.combine(d, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def fetch_activity(repo: str, date: date, github_token: str = None) -> dict:
    repo_normalized = _normalize_repo(repo)
    since, until = _date_to_utc_range(date)

    gh = Github(retry=None) if not github_token else Github(github_token, retry=None)

    try:
        gh_repo = gh.get_repo(repo_normalized)
    except GithubException as e:
        if e.status == 404:
            raise GitHubNotFoundError(f"Repository not found: {repo}") from e
        if e.status == 403:
            if "rate limit" in str(e.data).lower():
                raise GitHubError(f"GitHub rate limit exceeded for: {repo}") from e
            raise GitHubPermissionError(f"Permission denied for repository: {repo}") from e
        raise GitHubError(f"GitHub API error: {e}") from e

    try:
        commits_page = gh_repo.get_commits(since=since, until=until)
    except GithubException as e:
        if e.status == 404:
            raise GitHubNotFoundError(f"Repository not found or no commits: {repo}") from e
        if e.status == 403:
            if "rate limit" in str(e.data).lower():
                raise GitHubError(f"GitHub rate limit exceeded for: {repo}") from e
            raise GitHubPermissionError(f"Permission denied: {repo}") from e
        raise GitHubError(f"GitHub API error: {e}") from e

    commits_list = list(commits_page)

    commits = []
    total_additions = 0
    total_deletions = 0

    for commit in commits_list:
        additions = commit.stats.additions
        deletions = commit.stats.deletions
        total_additions += additions
        total_deletions += deletions
        commits.append({
            "sha": commit.sha,
            "message": commit.commit.message,
            "additions": additions,
            "deletions": deletions,
            "files": len(list(commit.files)),
        })

    try:
        pulls = list(gh_repo.get_pulls(state="all"))
    except GithubException as e:
        # PR 数据为辅助指标：拉取失败（限流/权限）不致命，置零继续
        import logging
        logging.getLogger(__name__).warning("PR 拉取失败 %s: %s", repo, e)
        pulls = []
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("PR 拉取失败 %s: %s", repo, e)
        pulls = []

    prs_opened = sum(1 for p in pulls if p.state == "open")
    prs_merged = sum(1 for p in pulls if p.state == "merged")

    return {
        "commits_count": len(commits),
        "commits": commits,
        "prs_opened": prs_opened,
        "prs_merged": prs_merged,
        "loc_additions": total_additions,
        "loc_deletions": total_deletions,
    }
