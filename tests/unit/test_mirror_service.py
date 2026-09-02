import sys
import os
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest


def _git(cwd, *args, env_extra=None):
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "tester")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@t.com")
    env.setdefault("GIT_COMMITTER_NAME", "tester")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@t.com")
    if env_extra:
        env.update(env_extra)
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture
def origin_repo(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-b", "main")
    (origin / "main.py").write_text("print('hello')\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "init project")
    return origin


@pytest.fixture
def mirrors_dir(tmp_path):
    d = tmp_path / "mirrors"
    d.mkdir()
    return d


class TestEnsureMirror:

    def test_clones_local_repo(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror
        path = ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))
        assert path.exists()
        assert (path / "HEAD").exists()

    def test_update_pulls_new_commits(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror
        ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))
        (origin_repo / "extra.py").write_text("x = 1\n")
        _git(origin_repo, "add", ".")
        _git(origin_repo, "commit", "-m", "second commit")
        ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))
        out = subprocess.run(
            ["git", "log", "--oneline"], capture_output=True, text=True,
            cwd=str(mirrors_dir / "origin.git"),
        ).stdout
        assert "second commit" in out

    def test_github_repo_maps_to_folder_name(self, mirrors_dir):
        from app.services.mirror_service import mirror_path
        p = mirror_path("owner/repo", mirror_dir=str(mirrors_dir))
        assert p == mirrors_dir / "owner__repo.git"


class TestSshFallbackUrl:

    @pytest.mark.parametrize("repo,expected", [
        ("https://github.com/PCashew/Harmony-smartcar",
         "git@ssh.github.com:443:PCashew/Harmony-smartcar.git"),
        ("https://github.com/X-196/Harmony_Car.git",
         "git@ssh.github.com:443:X-196/Harmony_Car.git"),
        ("ADVOT/STM-harmonyos-car",
         "git@ssh.github.com:443:ADVOT/STM-harmonyos-car.git"),
        ("https://github.com/phoenix23513/HarmonyOS_Car.git",
         "git@ssh.github.com:443:phoenix23513/HarmonyOS_Car.git"),
    ])
    def test_ssh_url_preserves_owner(self, repo, expected):
        from app.services.mirror_service import _to_ssh_url
        assert _to_ssh_url(repo) == expected

    def test_gitee_has_no_ssh_fallback(self):
        from app.services.mirror_service import _to_ssh_url
        assert _to_ssh_url("https://gitee.com/owner/repo") == ""


class TestMirrorPathSuffixStripping:

    @pytest.mark.parametrize("repo,expected", [
        ("https://github.com/lqs_linzh/unmanned-vehicle-project",
         "unmanned-vehicle-project.git"),
        ("https://github.com/a/mygit", "mygit.git"),
        ("https://github.com/a/project.git", "project.git"),
        ("https://github.com/a/tigg", "tigg.git"),
    ])
    def test_only_dot_git_suffix_stripped(self, repo, expected, mirrors_dir):
        from app.services.mirror_service import mirror_path
        assert mirror_path(repo, mirror_dir=str(mirrors_dir)).name == expected


class TestBrokenMirrorNotReusedAsCache:
    """空壳镜像（有 HEAD 文件但零 commit）必须重建，不得当成有效缓存复用。"""

    def test_mirror_without_refs_is_rebuilt(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror
        broken = mirrors_dir / "origin.git"
        broken.mkdir(parents=True)
        (broken / "HEAD").write_text("ref: refs/heads/main\n")

        path = ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))

        refs = subprocess.run(
            ["git", "for-each-ref"], capture_output=True, text=True, cwd=str(path),
        ).stdout.strip()
        assert refs, "空壳镜像应被重建为含 ref 的可用镜像"

    def test_valid_mirror_still_reused(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror
        first = ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))
        marker = first / "REUSE_MARKER"
        marker.write_text("x")

        again = ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))

        assert again == first
        assert marker.exists(), "有效镜像不应被删除重建"


class TestSshFallbackSuccessReturns:

    def test_ssh_fallback_success_returns_path(self, origin_repo, mirrors_dir, monkeypatch):
        import app.services.mirror_service as ms
        real_run_git = ms._run_git
        calls = []

        def fake_run_git(cwd, *args, **kwargs):
            if args and args[0] == "clone":
                calls.append(args)
                if len(calls) == 1:
                    raise ms.GitMirrorError("HTTPS 克隆失败")
                return real_run_git(cwd, "clone", "--mirror", str(origin_repo), args[-1])
            return real_run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(ms, "_run_git", fake_run_git)
        monkeypatch.setattr(ms, "_to_ssh_url", lambda r: "git@ssh.github.com:443:o/r.git")

        path = ms.ensure_mirror("https://github.com/o/r", mirror_dir=str(mirrors_dir))

        assert len(calls) == 2, "应先试 HTTPS 再回退 SSH"
        assert path.exists()


class TestExtractDayActivity:

    def test_counts_todays_commits_with_numstat(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror, extract_day_activity
        from datetime import date
        (origin_repo / "feature.py").write_text("def login():\n    return True\n")
        _git(origin_repo, "add", ".")
        _git(origin_repo, "commit", "-m", "feat: 完成登录函数")
        ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))

        result = extract_day_activity(
            str(origin_repo), date.today(), mirror_dir=str(mirrors_dir)
        )
        assert result["commits_count"] >= 2
        msgs = [c["message"] for c in result["commits"]]
        assert any("完成登录函数" in m for m in msgs)
        assert result["loc_additions"] > 0

    def test_extracts_code_diff_within_budget(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror, extract_day_activity
        from datetime import date
        body = "\n".join(f"line_{i} = {i}" for i in range(50))
        (origin_repo / "big.py").write_text(body + "\n")
        _git(origin_repo, "add", ".")
        _git(origin_repo, "commit", "-m", "feat: big module")
        ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))

        result = extract_day_activity(
            str(origin_repo), date.today(), mirror_dir=str(mirrors_dir),
            max_diff_chars=2000,
        )
        assert len(result["code_diffs"]) > 0
        total = sum(len(d["patch"]) for d in result["code_diffs"])
        assert total <= 2000 + 500

    def test_diff_contains_added_code(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror, extract_day_activity
        from datetime import date
        (origin_repo / "login.py").write_text("TOKEN = 'abc'\n")
        _git(origin_repo, "add", ".")
        _git(origin_repo, "commit", "-m", "feat: token")
        ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))

        result = extract_day_activity(
            str(origin_repo), date.today(), mirror_dir=str(mirrors_dir),
            max_diff_chars=8000,
        )
        all_patch = "".join(d["patch"] for d in result["code_diffs"])
        assert "TOKEN" in all_patch

    def test_empty_repo_returns_zeros(self, tmp_path, mirrors_dir):
        from app.services.mirror_service import ensure_mirror, extract_day_activity
        from datetime import date
        empty = tmp_path / "empty"
        empty.mkdir()
        _git(empty, "init", "-b", "main")
        ensure_mirror(str(empty), mirror_dir=str(mirrors_dir))

        result = extract_day_activity(str(empty), date.today(), mirror_dir=str(mirrors_dir))
        assert result["commits_count"] == 0
        assert result["code_diffs"] == []
        assert result["loc_additions"] == 0

    def test_other_day_returns_zeros(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror, extract_day_activity
        from datetime import date, timedelta
        ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))
        result = extract_day_activity(
            str(origin_repo), date.today() + timedelta(days=3650),
            mirror_dir=str(mirrors_dir),
        )
        assert result["commits_count"] == 0

    def test_month_end_date_does_not_overflow(self, origin_repo, mirrors_dir):
        """月末日期（如 12/31）计算次日不得抛 ValueError（回归：replace(day+1) 溢出）。"""
        from app.services.mirror_service import ensure_mirror, extract_day_activity
        from datetime import date
        ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))
        result = extract_day_activity(
            str(origin_repo), date(2026, 12, 31), mirror_dir=str(mirrors_dir)
        )
        assert result["commits_count"] == 0
        assert result["code_diffs"] == []

class TestExtractSnapshot:

    def test_returns_source_files_with_content(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror, extract_snapshot
        (origin_repo / "service").mkdir()
        (origin_repo / "service" / "core.py").write_text("def core():\n    return 42\n")
        (origin_repo / "README.md").write_text("# demo\n")
        _git(origin_repo, "add", ".")
        _git(origin_repo, "commit", "-m", "add module")
        ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))

        result = extract_snapshot(str(origin_repo), mirror_dir=str(mirrors_dir))
        paths = {f["path"] for f in result["files"]}
        assert "main.py" in paths
        assert "service/core.py" in paths

    def test_content_truncated_per_file(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror, extract_snapshot
        big = "\n".join(f"x{i} = {i}" for i in range(500))
        (origin_repo / "big.py").write_text(big)
        _git(origin_repo, "add", ".")
        _git(origin_repo, "commit", "-m", "big file")
        ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))

        result = extract_snapshot(
            str(origin_repo), mirror_dir=str(mirrors_dir), max_file_chars=300
        )
        target = next(f for f in result["files"] if f["path"] == "big.py")
        assert len(target["content"]) <= 300 + 20
        assert target["truncated"] is True

    def test_total_budget_respected(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror, extract_snapshot
        for i in range(5):
            (origin_repo / f"mod_{i}.py").write_text("\n".join(f"v{j}={j}" for j in range(200)) + "\n")
            _git(origin_repo, "add", ".")
            _git(origin_repo, "commit", "-m", f"mod {i}")
        ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))

        result = extract_snapshot(
            str(origin_repo), mirror_dir=str(mirrors_dir), max_total_chars=1500
        )
        total = sum(len(f["content"]) for f in result["files"])
        assert total <= 1500 + len(result["files"]) * 30
        assert result["total_files_in_repo"] >= 5

    def test_binary_and_junk_skipped(self, origin_repo, mirrors_dir):
        from app.services.mirror_service import ensure_mirror, extract_snapshot
        (origin_repo / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
        (origin_repo / "node_modules").mkdir()
        (origin_repo / "node_modules" / "dep.js").write_text("var a=1;\n")
        (origin_repo / "app.js").write_text("console.log(1);\n")
        _git(origin_repo, "add", ".")
        _git(origin_repo, "commit", "-m", "assets")
        ensure_mirror(str(origin_repo), mirror_dir=str(mirrors_dir))

        result = extract_snapshot(str(origin_repo), mirror_dir=str(mirrors_dir))
        paths = {f["path"] for f in result["files"]}
        assert "image.png" not in paths
        assert any(p.startswith("node_modules/") for p in paths) is False
        assert "app.js" in paths
