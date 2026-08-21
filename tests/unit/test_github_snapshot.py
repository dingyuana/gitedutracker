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
