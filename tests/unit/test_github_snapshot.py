import sys
import os
import pytest
from datetime import date, datetime, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlmodel import SQLModel, create_engine, Session, select
from app.models import Student, GithubActivity


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def session(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def students(session):
    s1 = Student(name='张三', email='zs@example.com', github_repo='zs/myrepo')
    s2 = Student(name='李四', email='ls@example.com', github_repo='ls/myrepo')
    session.add(s1)
    session.add(s2)
    session.commit()
    session.refresh(s1)
    session.refresh(s2)
    return [s1, s2]


@pytest.fixture
def mock_activity_result():
    return {
        "commits_count": 3,
        "commits": [
            {"sha": "abc", "message": "feat: add login", "additions": 50, "deletions": 10, "files": 2}
        ],
        "prs_opened": 1,
        "prs_merged": 0,
        "loc_additions": 50,
        "loc_deletions": 10,
    }


class TestSyncDaySuccess:

    @patch("app.services.github_snapshot.fetch_activity")
    def test_two_students_two_snapshots(self, mock_fetch, session, students, mock_activity_result):
        from app.services.github_snapshot import sync_day
        mock_fetch.return_value = mock_activity_result

        target = date(2026, 8, 21)
        result = sync_day(target, session)

        assert result == 2
        activities = session.exec(
            select(GithubActivity).where(GithubActivity.date == target)
        ).all()
        assert len(activities) == 2
        for a in activities:
            assert a.status == "ok"
            assert a.commits_count == 3
            assert a.prs_opened == 1
            assert a.prs_merged == 0
            assert a.loc_additions == 50
            assert a.loc_deletions == 10
            assert a.fetched_at is not None

    @patch("app.services.github_snapshot.fetch_activity")
    def test_upsert_creates_new_record(self, mock_fetch, session, students, mock_activity_result):
        from app.services.github_snapshot import sync_day
        mock_fetch.return_value = mock_activity_result

        target = date(2026, 8, 21)
        sync_day(target, session)

        activities = session.exec(
            select(GithubActivity).where(GithubActivity.date == target)
        ).all()
        assert len(activities) == 2

    @patch("app.services.github_snapshot.fetch_activity")
    def test_upsert_updates_existing_record(self, mock_fetch, session, students, mock_activity_result):
        from app.services.github_snapshot import sync_day
        mock_fetch.return_value = mock_activity_result

        target = date(2026, 8, 21)
        s1 = session.exec(select(Student).where(Student.name == '张三')).first()

        existing = GithubActivity(
            student_id=s1.id,
            date=target,
            commits_count=0,
            status='pending',
        )
        session.add(existing)
        session.commit()

        sync_day(target, session)

        updated = session.exec(
            select(GithubActivity).where(
                GithubActivity.student_id == s1.id,
                GithubActivity.date == target,
            )
        ).first()
        assert updated.status == "ok"
        assert updated.commits_count == 3


class TestSyncDayFailure:

    @patch("app.services.github_snapshot.fetch_activity")
    def test_one_student_failure_marks_failed(self, mock_fetch, session, students, mock_activity_result):
        from app.services.github_snapshot import sync_day
        from app.models import Student
        mock_fetch.side_effect = [mock_activity_result, Exception("GitHub API error")]

        target = date(2026, 8, 21)
        result = sync_day(target, session)

        assert result == 1
        s1 = session.exec(select(Student).where(Student.name == '张三')).first()
        s2 = session.exec(select(Student).where(Student.name == '李四')).first()

        a1 = session.exec(
            select(GithubActivity).where(
                GithubActivity.student_id == s1.id,
                GithubActivity.date == target,
            )
        ).first()
        a2 = session.exec(
            select(GithubActivity).where(
                GithubActivity.student_id == s2.id,
                GithubActivity.date == target,
            )
        ).first()

        assert a1.status == "ok"
        assert a2.status == "failed"
        assert a2.saved_context_json is not None

    @patch("app.services.github_snapshot.fetch_activity")
    def test_all_students_fail(self, mock_fetch, session, students):
        from app.services.github_snapshot import sync_day
        mock_fetch.side_effect = Exception("Total failure")

        target = date(2026, 8, 21)
        result = sync_day(target, session)

        assert result == 0
        activities = session.exec(select(GithubActivity).where(GithubActivity.date == target)).all()
        assert len(activities) == 2
        for a in activities:
            assert a.status == "failed"

    @patch("app.services.github_snapshot.fetch_activity")
    def test_return_count_correct(self, mock_fetch, session, students, mock_activity_result):
        from app.services.github_snapshot import sync_day
        mock_fetch.side_effect = [
            mock_activity_result,
            Exception("boom"),
        ]

        target = date(2026, 8, 21)
        result = sync_day(target, session)

        assert result == 1


class TestSyncDayEmpty:

    @patch("app.services.github_snapshot.fetch_activity")
    def test_no_students_returns_zero(self, mock_fetch, session):
        from app.services.github_snapshot import sync_day

        target = date(2026, 8, 21)
        result = sync_day(target, session)

        assert result == 0
        mock_fetch.assert_not_called()


class TestSyncPacing:

    def test_sleeps_between_students(self, session):
        from unittest.mock import patch, MagicMock
        from app.services import github_snapshot
        from app.models import Student
        from datetime import date

        s1 = Student(name='甲', email='a@x.com', github_repo='a/r')
        s2 = Student(name='乙', email='b@x.com', github_repo='b/r')
        session.add_all([s1, s2])
        session.commit()

        with patch.object(github_snapshot, "fetch_activity", return_value={
            "commits_count": 0, "commits": [], "prs_opened": 0,
            "prs_merged": 0, "loc_additions": 0, "loc_deletions": 0,
        }), patch.object(github_snapshot.time, "sleep") as mock_sleep:
            github_snapshot.sync_day(date(2026, 8, 21), session=session)

        assert mock_sleep.call_count >= 1


class TestRateLimitRetry:

    def test_rate_limit_error_retries_once_then_succeeds(self, session):
        from unittest.mock import patch, MagicMock, call
        from app.services import github_snapshot
        from app.models import Student
        from datetime import date

        s1 = Student(name='甲', email='rl@x.com', github_repo='a/r')
        session.add(s1)
        session.commit()

        responses = [Exception("GitHub rate limit exceeded for: a/r"), {
            "commits_count": 1, "commits": [], "prs_opened": 0,
            "prs_merged": 0, "loc_additions": 5, "loc_deletions": 1,
        }]

        def fake_fetch(**kwargs):
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with patch.object(github_snapshot, "fetch_activity", side_effect=fake_fetch), \
             patch.object(github_snapshot.time, "sleep") as mock_sleep:
            count = github_snapshot.sync_day(date(2026, 8, 21), session=session)

        assert count == 1
        assert mock_sleep.call_args_list[-1] == call(github_snapshot.RATE_LIMIT_COOLDOWN_SECONDS)

    def test_non_rate_limit_fails_fast(self, session):
        from unittest.mock import patch
        from app.services import github_snapshot
        from app.models import Student, GithubActivity
        from datetime import date

        s1 = Student(name='乙', email='nf@x.com', github_repo='b/r')
        session.add(s1)
        session.commit()

        with patch.object(github_snapshot, "fetch_activity", side_effect=Exception("Repository not found")), \
             patch.object(github_snapshot.time, "sleep") as mock_sleep:
            github_snapshot.sync_day(date(2026, 8, 21), session=session)

        act = session.exec(select(GithubActivity)).first()
        assert act.status == "failed"
        assert len(mock_sleep.call_args_list) <= 1


class TestReuseOkCache:

    def test_ok_activity_not_refetched(self, session):
        from unittest.mock import patch
        from app.services import github_snapshot
        from app.models import Student, GithubActivity
        from datetime import date

        s1 = Student(name='甲', email='cache@x.com', github_repo='c/r')
        session.add(s1)
        session.commit()
        session.add(GithubActivity(student_id=s1.id, date=date(2026, 8, 21), status="ok", commits_count=3))
        session.commit()

        with patch.object(github_snapshot, "fetch_activity") as mock_fetch:
            count = github_snapshot.sync_day(date(2026, 8, 21), session=session)

        mock_fetch.assert_not_called()
        assert count == 1

    def test_failed_activity_is_refetched(self, session):
        from unittest.mock import patch
        from app.services import github_snapshot
        from app.models import Student, GithubActivity
        from datetime import date

        s1 = Student(name='乙', email='refetch@x.com', github_repo='d/r')
        session.add(s1)
        session.commit()
        session.add(GithubActivity(student_id=s1.id, date=date(2026, 8, 21), status="failed"))
        session.commit()

        with patch.object(github_snapshot, "fetch_activity", return_value={
            "commits_count": 2, "commits": [], "prs_opened": 0,
            "prs_merged": 0, "loc_additions": 10, "loc_deletions": 2,
        }):
            github_snapshot.sync_day(date(2026, 8, 21), session=session)

        act = session.exec(select(GithubActivity)).first()
        assert act.status == "ok"
        assert act.commits_count == 2


class TestMirrorFirstSync:

    def test_uses_mirror_before_api(self, session):
        from unittest.mock import patch
        from app.services import github_snapshot
        from app.models import Student, GithubActivity
        from datetime import date

        s1 = Student(name='甲', email='mf@x.com', github_repo='m/r')
        session.add(s1)
        session.commit()

        mirror_data = {"commits_count": 4, "commits": [{"sha": "x", "message": "m",
                        "additions": 30, "deletions": 5}],
                       "loc_additions": 30, "loc_deletions": 5}

        with patch.object(github_snapshot, "_fetch_via_mirror", return_value=mirror_data), \
             patch.object(github_snapshot, "fetch_activity") as mock_api:
            count = github_snapshot.sync_day(date(2026, 8, 21), session=session)

        mock_api.assert_not_called()
        assert count == 1
        act = session.exec(select(GithubActivity)).first()
        assert act.status == "ok"
        assert act.commits_count == 4

    def test_falls_back_to_api_when_mirror_fails(self, session):
        from unittest.mock import patch
        from app.services import github_snapshot
        from app.models import Student, GithubActivity
        from datetime import date

        s1 = Student(name='乙', email='fb@x.com', github_repo='f/r')
        session.add(s1)
        session.commit()

        api_data = {"commits_count": 1, "commits": [], "prs_opened": 0,
                    "prs_merged": 0, "loc_additions": 3, "loc_deletions": 1}

        with patch.object(github_snapshot, "_fetch_via_mirror", return_value=None), \
             patch.object(github_snapshot, "fetch_activity", return_value=api_data):
            count = github_snapshot.sync_day(date(2026, 8, 21), session=session)

        assert count == 1
