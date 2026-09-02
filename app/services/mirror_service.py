from __future__ import annotations

import subprocess
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_MIRROR_DIR = "data/mirrors"
MAX_DIFF_COMMITS = 5
SNAPSHOT_SKIP_DIRS = ("node_modules/", "dist/", "build/", ".idea/", "__pycache__/", "vendor/")
SNAPSHOT_BINARY_EXT = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".pdf", ".zip",
    ".gz", ".tar", ".rar", ".7z", ".exe", ".dll", ".so", ".dylib",
    ".mp3", ".mp4", ".wav", ".woff", ".woff2", ".ttf", ".db", ".sqlite",
)
_RECORD_SEP = "\x1e"


class GitMirrorError(Exception):
    pass


def _run_git(cwd: str | Path, *args: str, timeout: int = 60) -> str:
    result = subprocess.run(
        ["git", "-c", "http.version=HTTP/1.1", *args],
        cwd=str(cwd), capture_output=True, timeout=timeout
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()[:200]
        raise GitMirrorError(f"git {' '.join(args[:2])} 失败: {stderr}")
    return result.stdout.decode("utf-8", errors="replace")


def detect_platform(repo: str) -> str:
    """根据仓库 URL 或 owner/repo 格式判断平台: github / gitee"""
    r = repo.strip().lower()
    if "gitee.com" in r:
        return "gitee"
    return "github"


def _to_ssh_url(repo: str) -> str:
    """GitHub SSH over port 443 URL（Gitee 不使用此回退）"""
    platform = detect_platform(repo)
    if platform == "gitee":
        return ""  # Gitee 不支持 SSH over 443

    cleaned = repo.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if "://" in cleaned or cleaned.startswith(("/", "~")) or cleaned[1:3] == ":\\":
        cleaned = cleaned.split("://")[-1].split("/")[-1]
    else:
        cleaned = cleaned.replace("/", "__")
    return f"git@ssh.github.com:443:{cleaned}.git"


def _to_remote_url(repo: str) -> str:
    repo = repo.strip()
    if repo.endswith(".git"):
        repo = repo[:-4]
    if repo.startswith(("http://", "https://", "git@", "/")) or repo[1:3] == ":\\":
        return repo
    platform = detect_platform(repo)
    if platform == "gitee":
        return f"https://gitee.com/{repo}.git"
    return f"https://github.com/{repo}.git"


def mirror_path(repo: str, mirror_dir: str | None = None) -> Path:
    base = Path(mirror_dir or DEFAULT_MIRROR_DIR).resolve()
    cleaned = repo.strip().rstrip("/")
    if "://" in cleaned or cleaned.startswith(("/", "~")) or cleaned[1:3] == ":\\":
        name = cleaned.split("://")[-1].rstrip(".git").split("/")[-1]
        if not name:
            raise GitMirrorError(f"无法确定镜像名: {repo}")
    else:
        name = cleaned[:-4] if cleaned.endswith(".git") else cleaned
        name = name.replace("/", "__")
    return base / f"{name}.git"


def ensure_mirror(repo: str, mirror_dir: str | None = None) -> Path:
    path = mirror_path(repo, mirror_dir)

    if path.exists():
        if (path / "HEAD").exists():
            try:
                _run_git(path, "remote", "update", "--prune", timeout=10)
            except GitMirrorError as e:
                # 更新失败不影响读取历史数据，但记录以便排查网络/权限问题
                logging.getLogger(__name__).warning(
                    "镜像更新失败（继续用历史数据）%s: %s", path, e
                )
            return path
        import shutil
        shutil.rmtree(path, ignore_errors=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    url = _to_remote_url(repo)
    try:
        _run_git(path.parent, "clone", "--mirror", url, str(path), timeout=180)
    except GitMirrorError:
        # 回退 SSH over 443（仅 GitHub，Gitee 不使用此回退）
        ssh_url = _to_ssh_url(repo)
        if ssh_url:
            try:
                _run_git(path.parent, "clone", "--mirror", ssh_url, str(path), timeout=180)
            except GitMirrorError as e2:
                raise GitMirrorError(f"镜像克隆失败 {repo} (HTTPS/SSH 均失败)") from e2
        raise
    return path


def extract_day_activity(
    repo: str,
    target_date: date,
    mirror_dir: str | None = None,
    max_diff_chars: int = 4000,
) -> dict:
    path = ensure_mirror(repo, mirror_dir)

    since = datetime.combine(target_date, datetime.min.time()).isoformat()
    until = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).isoformat()

    log_raw = _run_git(
        path,
        "log", "--all",
        f"--since={since}", f"--until={until}",
        "--numstat",
        f"--format={_RECORD_SEP}%H%x1f%s",
    )

    commits: list[dict] = []
    loc_additions = 0
    loc_deletions = 0

    for record in log_raw.split(_RECORD_SEP):
        record = record.strip("\n")
        if not record.strip():
            continue
        lines = record.splitlines()
        header = lines[0]
        if "\x1f" not in header:
            continue
        sha, message = header.split("\x1f", 1)
        additions = deletions = 0
        for stat_line in lines[1:]:
            parts = stat_line.split("\t")
            if len(parts) < 3:
                continue
            add_s, del_s = parts[0], parts[1]
            if add_s.isdigit():
                additions += int(add_s)
            if del_s.isdigit():
                deletions += int(del_s)
        commits.append({
            "sha": sha[:10],
            "message": message.splitlines()[0] if message else "",
            "additions": additions,
            "deletions": deletions,
        })
        loc_additions += additions
        loc_deletions += deletions

    code_diffs = _collect_diffs(path, commits, max_diff_chars)

    return {
        "commits_count": len(commits),
        "commits": commits,
        "loc_additions": loc_additions,
        "loc_deletions": loc_deletions,
        "code_diffs": code_diffs,
    }


def extract_snapshot(
    repo: str,
    mirror_dir: str | None = None,
    max_file_chars: int = 1500,
    max_total_chars: int = 12000,
    ref: str = "HEAD",
) -> dict:
    """从本地镜像提取全项目源码快照（B 方案：全量代码审核用）"""
    path = ensure_mirror(repo, mirror_dir)

    listing = _run_git(path, "ls-tree", "-r", "--name-only", ref)
    all_files = [line for line in listing.splitlines() if line.strip()]

    files: list[dict] = []
    used = 0
    for rel in all_files:
        if len(rel.split("/")) >= 2 and f"{rel.split('/')[0]}/" in SNAPSHOT_SKIP_DIRS:
            continue
        if any(skip in rel for skip in SNAPSHOT_SKIP_DIRS):
            continue
        if rel.lower().endswith(SNAPSHOT_BINARY_EXT):
            continue

        remaining = max_total_chars - used
        if remaining <= 100:
            break
        file_budget = min(max_file_chars, remaining)
        try:
            content = _run_git(path, "show", f"{ref}:{rel}")
        except GitMirrorError:
            continue
        if "\x00" in content:
            continue
        truncated = False
        if len(content) > file_budget:
            content = content[:file_budget]
            truncated = True
        used += len(content)
        files.append({
            "path": rel,
            "content": content,
            "truncated": truncated,
        })

    return {
        "files": files,
        "total_files_in_repo": len(all_files),
    }


def _collect_diffs(path: Path, commits: list[dict], budget: int) -> list[dict]:
    diffs: list[dict] = []
    used = 0
    for c in commits[:MAX_DIFF_COMMITS]:
        if used >= budget:
            break
        try:
            patch = _run_git(path, "show", c["sha"], "--format=", "--unified=1")
        except GitMirrorError:
            continue
        remaining = budget - used
        if len(patch) > remaining:
            patch = patch[:remaining] + "\n…(截断)"
        used += len(patch)
        diffs.append({
            "sha": c["sha"],
            "message": c["message"],
            "patch": patch,
        })
    return diffs
