import sys
import os
import json
import pytest
from datetime import date, datetime, timezone
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlmodel import SQLModel, create_engine, Session, select
from app.models import (
    Student, Project, DailyPlan, GithubActivity, Assessment, ScoringConfig,
)


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def session(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def seed_data(session):
    s1 = Student(name='张三', email='zs@example.com', github_repo='zs/myrepo')
    s2 = Student(name='李四', email='ls@example.com', github_repo='ls/myrepo')
    session.add(s1)
    session.add(s2)
    session.commit()
    session.refresh(s1)
    session.refresh(s2)

    p1 = Project(name='项目A')
    session.add(p1)
    session.commit()
    session.refresh(p1)

    plan_all = DailyPlan(
        project_id=p1.id,
        date=date(2026, 8, 21),
        content='完成登录模块',
        student_id=None,
    )
    session.add(plan_all)
    session.commit()
    session.refresh(plan_all)

    config = ScoringConfig(
        w_volume=0.333, w_quality=0.333, w_match=0.333,
        loc_threshold=100, schedule_bonus=5.0, schedule_penalty=-5.0,
    )
    session.add(config)
    session.commit()
    session.refresh(config)

    target = date(2026, 8, 21)
    for s in [s1, s2]:
        activity = GithubActivity(
            student_id=s.id,
            date=target,
            commits_count=3,
            commits_json=json.dumps([
                {"sha": "abc123", "message": "feat: add login", "additions": 50, "deletions": 10}
            ], ensure_ascii=False),
            prs_opened=1,
            prs_merged=0,
            loc_additions=50,
            loc_deletions=10,
            status="ok",
        )
        session.add(activity)
    session.commit()

    return {
        's1': s1, 's2': s2, 'p1': p1,
        'plan_all': plan_all, 'config': config,
        'target': target,
    }


@pytest.fixture
def mock_settings():
    from app.config import Settings
    s = Settings()
    s.llm_base_url = "https://api.openai.com/v1"
    s.llm_api_key = "sk-test"
    s.llm_model = "gpt-4o-mini"
    s.llm_context_max_chars = 12000
    return s


@pytest.fixture
def mock_ai_response():
    return {
        "quality_score": 85,
        "match_score": 90,
        "completion": True,
        "schedule_status": "ontime",
        "comment": "表现良好，继续努力",
        "reasoning": "按时完成",
    }


class TestRunTodayTriggersEmail:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_run_today_calls_send_daily_comments_after_scoring(
        self, mock_sync_day, mock_score_student, mock_send_daily_comments,
        session, seed_data, mock_settings, mock_ai_response
    ):
        from app.services.pipeline import run_today

        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response
        mock_send_daily_comments.return_value = None

        run_today(seed_data['target'], session=session)

        mock_send_daily_comments.assert_called_once_with(
            seed_data['target'], session
        )

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_send_daily_comments_receives_target_date_and_session(
        self, mock_sync_day, mock_score_student, mock_send_daily_comments,
        session, seed_data, mock_settings, mock_ai_response
    ):
        from app.services.pipeline import run_today

        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response
        mock_send_daily_comments.return_value = None

        run_today(seed_data['target'], session=session)

        call_args = mock_send_daily_comments.call_args
        assert call_args[0][0] == seed_data['target']
        assert call_args[0][1] is session


class TestEmailFailureDoesNotAffectScoring:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_email_failure_does_not_rollback_assessments(
        self, mock_sync_day, mock_score_student, mock_send_daily_comments,
        session, seed_data, mock_settings, mock_ai_response
    ):
        from app.services.pipeline import run_today

        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response
        mock_send_daily_comments.side_effect = Exception("SMTP failure")

        result = run_today(seed_data['target'], session=session)

        assert result["success"] >= 1
        assert result["failed"] == 0

        assessments = session.exec(
            select(Assessment).where(Assessment.date == seed_data['target'])
        ).all()
        assert len(assessments) >= 1
        for a in assessments:
            assert a.status == "done"
            assert a.total_score is not None

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_email_failure_logged_but_pipeline_continues(
        self, mock_sync_day, mock_score_student, mock_send_daily_comments,
        session, seed_data, mock_settings, mock_ai_response
    ):
        from app.services.pipeline import run_today

        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response
        mock_send_daily_comments.side_effect = ConnectionError("network down")

        result = run_today(seed_data['target'], session=session)

        assert result["success"] >= 1
        assessments = session.exec(
            select(Assessment).where(Assessment.date == seed_data['target'])
        ).all()
        assert all(a.status == "done" for a in assessments)
