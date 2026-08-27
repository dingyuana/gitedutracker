from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from github import Github
from github import GithubException

from app.services.mirror_service import detect_platform


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


def fetch_gitee_activity(repo: str, target_date: date) -> dict:
    import urllib.request
    import urllib.parse
    import json
    import logging

    repo_normalized = _normalize_repo(repo)
    since, until = _date_to_utc_range(target_date)

    base = f"https://gitee.com/api/v5/repos/{repo_normalized}"
    commits_url = f"{base}/commits?since={since.isoformat()}&until={until.isoformat()}&per_page=100"

    try:
        req = urllib.request.Request(commits_url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            commits_data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise GitHubNotFoundError(f"Gitee 仓库不存在: {repo}") from e
        raise GitHubError(f"Gitee API error: {e.code} {e.reason}") from e
    except Exception as e:
        raise GitHubError(f"Gitee 请求失败: {e}") from e

    commits = []
    total_additions = 0
    total_deletions = 0

    for c in (commits_data if isinstance(commits_data, list) else []):
        sha = c.get("sha", "")
        message = c.get("commit", {}).get("message", "")
        stats = c.get("commit", {}).get("stats", {})
        additions = stats.get("additions", 0)
        deletions = stats.get("deletions", 0)
        total_additions += additions
        total_deletions += deletions
        commits.append({
            "sha": sha[:10],
            "message": message.splitlines()[0] if message else "",
            "additions": additions,
            "deletions": deletions,
            "files": 0,
        })

    prs_url = f"{base}/pulls?state=all&per_page=100"
    prs_opened = 0
    prs_merged = 0
    try:
        req = urllib.request.Request(prs_url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            prs_data = json.loads(resp.read().decode())
        for p in (prs_data if isinstance(prs_data, list) else []):
            state = p.get("state", "")
            merged = p.get("merged", False)
            if merged:
                prs_merged += 1
            elif state == "opened":
                prs_opened += 1
    except Exception:
        logging.getLogger(__name__).warning("Gitee PR 拉取失败 %s", repo)

    return {
        "commits_count": len(commits),
        "commits": commits,
        "prs_opened": prs_opened,
        "prs_merged": prs_merged,
        "loc_additions": total_additions,
        "loc_deletions": total_deletions,
    }


def fetch_activity_for_repo(repo: str, target_date: date, github_token: str = None) -> dict:
    platform = detect_platform(repo)
    if platform == "gitee":
        return fetch_gitee_activity(repo, target_date)
    return fetch_activity(repo, target_date, github_token)
