import sys
import os
import json
import pytest
from datetime import date, datetime, timedelta, timezone
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
    session.add_all([s1, s2])
    session.commit()
    session.refresh(s1)
    session.refresh(s2)

    p1 = Project(name='项目A')
    session.add(p1)
    session.commit()
    session.refresh(p1)

    config = ScoringConfig(
        w_volume=0.333, w_quality=0.333, w_match=0.333,
        loc_threshold=100, schedule_bonus=5.0, schedule_penalty=-5.0,
    )
    session.add(config)
    session.commit()
    session.refresh(config)

    return {
        's1': s1, 's2': s2, 'p1': p1, 'config': config,
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
        "comment": "表现良好",
        "reasoning": "按时完成",
    }


@pytest.fixture
def failed_assessment(session, seed_data):
    """Insert an Assessment with status='failed' and next_retry_at in the past."""
    now = datetime.now(timezone.utc)
    ctx = {
        "plan_content": "完成登录模块",
        "commits": [],
        "prs_opened": 0,
        "prs_merged": 0,
        "loc_additions": 0,
        "loc_deletions": 0,
        "student_id": seed_data['s1'].id,
        "date": str(date(2026, 8, 21)),
    }
    a = Assessment(
        student_id=seed_data['s1'].id,
        project_id=seed_data['p1'].id,
        date=date(2026, 8, 21),
        status='failed',
        next_retry_at=now - timedelta(hours=1),  # expired → eligible for retry
        saved_context_json=json.dumps(ctx, ensure_ascii=False),
        attempts=1,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


@pytest.fixture
def not_yet_due_assessment(session, seed_data):
    """Insert an Assessment with status='failed' but next_retry_at in the future."""
    future = datetime.now(timezone.utc) + timedelta(hours=5)
    ctx = {
        "plan_content": "完成登录模块",
        "commits": [],
        "prs_opened": 0,
        "prs_merged": 0,
        "loc_additions": 0,
        "loc_deletions": 0,
        "student_id": seed_data['s2'].id,
        "date": str(date(2026, 8, 21)),
    }
    a = Assessment(
        student_id=seed_data['s2'].id,
        project_id=seed_data['p1'].id,
        date=date(2026, 8, 21),
        status='failed',
        next_retry_at=future,
        saved_context_json=json.dumps(ctx, ensure_ascii=False),
        attempts=1,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


class TestAttemptScoreThreeFailures:

    @patch("app.services.retry_service.score_student")
    def test_all_three_failures_mark_assessment_failed_with_retry(self, mock_score_student, session, seed_data, mock_settings, failed_assessment):
        from app.services.retry_service import _attempt_score

        mock_score_student.side_effect = Exception("LLM error")

        result = _attempt_score(
            seed_data['s1'].id,
            failed_assessment.saved_context_json,
            session,
            mock_settings,
        )

        assert result is False

        session.refresh(failed_assessment)
        assert failed_assessment.status == "failed"
        assert failed_assessment.next_retry_at is not None
        expected = datetime.now(timezone.utc) + timedelta(hours=2)
        nrt = failed_assessment.next_retry_at
        if nrt.tzinfo is None:
            nrt = nrt.replace(tzinfo=timezone.utc)
        assert abs((nrt - expected).total_seconds()) < 5
        assert failed_assessment.saved_context_json is not None


class TestReaperSuccessAfterTimeAdvance:

    @patch("app.services.retry_service.score_student")
    def test_reaper_retries_expired_failed_and_marks_done(self, mock_score_student, session, seed_data, mock_settings, mock_ai_response, failed_assessment):
        from app.services.retry_service import retry_failed_assessments

        mock_score_student.return_value = mock_ai_response

        result = retry_failed_assessments(session=session)

        assert result == 1

        session.refresh(failed_assessment)
        assert failed_assessment.status == "done"
        assert failed_assessment.quality_score == 85
        assert failed_assessment.match_score == 90
        assert failed_assessment.total_score is not None
        assert failed_assessment.evaluated_at is not None


class TestReaperAlwaysFailsKeepsFailed:

    @patch("app.services.retry_service.score_student")
    def test_repeatedly_failing_assessment_stays_failed(self, mock_score_student, session, seed_data, mock_settings, failed_assessment):
        from app.services.retry_service import retry_failed_assessments

        mock_score_student.side_effect = Exception("persistent LLM failure")

        result = retry_failed_assessments(session=session)

        assert result == 1

        session.refresh(failed_assessment)
        assert failed_assessment.status == "failed"
        assert failed_assessment.next_retry_at is not None
        expected = datetime.now(timezone.utc) + timedelta(hours=2)
        nrt = failed_assessment.next_retry_at
        if nrt.tzinfo is None:
            nrt = nrt.replace(tzinfo=timezone.utc)
        assert abs((nrt - expected).total_seconds()) < 5
        assert failed_assessment.saved_context_json is not None


class TestReaperQueryDoesNotRetryNotYetDue:

    @patch("app.services.retry_service.score_student")
    def test_not_yet_due_assessment_is_unchanged(self, mock_score_student, session, seed_data, mock_settings, not_yet_due_assessment):
        from app.services.retry_service import retry_failed_assessments

        mock_score_student.return_value = {
            "quality_score": 85,
            "match_score": 90,
            "completion": True,
            "schedule_status": "ontime",
            "comment": "ok",
            "reasoning": "ok",
        }

        result = retry_failed_assessments(session=session)

        assert result == 0

        session.refresh(not_yet_due_assessment)
        assert not_yet_due_assessment.status == "failed"
        future_time = not_yet_due_assessment.next_retry_at
        if future_time.tzinfo is None:
            from datetime import timezone as _tz
            future_time = future_time.replace(tzinfo=_tz.utc)
        assert future_time > datetime.now(timezone.utc)

    @patch("app.services.retry_service.score_student")
    def test_only_expired_failed_assessments_are_retried(self, mock_score_student, session, seed_data, mock_settings, failed_assessment, not_yet_due_assessment, mock_ai_response):
        from app.services.retry_service import retry_failed_assessments

        mock_score_student.return_value = mock_ai_response

        result = retry_failed_assessments(session=session)

        assert result == 1  # only the expired one

        session.refresh(failed_assessment)
        assert failed_assessment.status == "done"

        session.refresh(not_yet_due_assessment)
        assert not_yet_due_assessment.status == "failed"


class TestScoreWritebackCompleteness:

    @patch("app.services.retry_service.score_student")
    def test_successful_retry_writes_volume_and_adjustment(
            self, mock_score, session, seed_data, mock_settings):
        from app.services.retry_service import _attempt_score
        d = date(2026, 9, 2)
        a = Assessment(student_id=seed_data['s1'].id, project_id=seed_data['p1'].id,
                       date=d, eval_type='full', status='failed', attempts=2)
        session.add(a)
        session.commit()

        mock_score.return_value = {
            "quality_score": 80, "match_score": 90, "schedule_status": "behind",
            "bonus": 3, "comment": "c",
        }
        ctx = json.dumps({"eval_mode": "full", "project_id": seed_data['p1'].id,
                          "date": str(d), "loc_additions": 60, "loc_deletions": 40})

        ok = _attempt_score(seed_data['s1'].id, ctx, session, mock_settings, target_date=d)

        assert ok is True
        session.refresh(a)
        assert a.volume_score == 100.0, "loc=100/threshold=100 → 100 分，不得为 None"
        assert a.schedule_adjustment == -5.0, "behind 必须回写 penalty，不得停留 0.0"
        assert a.attempts == 3, "重试路径必须累加 attempts"

    @patch("app.services.retry_service.score_student")
    def test_failure_only_marks_matching_eval_type(
            self, mock_score, session, seed_data, mock_settings):
        from app.services.retry_service import _attempt_score
        d = date(2026, 9, 2)
        diff_a = Assessment(student_id=seed_data['s1'].id, project_id=seed_data['p1'].id,
                            date=d, eval_type='diff', status='done', total_score=77.0)
        full_a = Assessment(student_id=seed_data['s1'].id, project_id=seed_data['p1'].id,
                            date=d, eval_type='full', status='failed')
        session.add_all([diff_a, full_a])
        session.commit()

        mock_score.side_effect = RuntimeError("llm down")
        ctx = json.dumps({"eval_mode": "full", "project_id": seed_data['p1'].id,
                          "date": str(d)})

        _attempt_score(seed_data['s1'].id, ctx, session, mock_settings, target_date=d)

        session.refresh(diff_a)
        session.refresh(full_a)
        assert diff_a.status == 'done', "diff 记录不得被 full 的失败波及"
        assert diff_a.total_score == 77.0
        assert full_a.status == 'failed'
        assert full_a.fail_reason == 'llm'


class TestRetryIntervalsByReason:

    def test_repo_pull_uses_one_hour(self, session, seed_data):
        from app.services.retry_service import arm_retry
        a = Assessment(student_id=seed_data['s1'].id, project_id=seed_data['p1'].id,
                       date=date(2026, 9, 2), eval_type='full', attempts=1)
        arm_retry(a, "repo_pull")
        delta = a.next_retry_at - datetime.now(timezone.utc)
        assert 0.9 < delta.total_seconds() / 3600 < 1.1
        assert a.status == 'failed'
        assert a.fail_reason == 'repo_pull'

    def test_llm_uses_two_hours(self, session, seed_data):
        from app.services.retry_service import arm_retry
        a = Assessment(student_id=seed_data['s1'].id, project_id=seed_data['p1'].id,
                       date=date(2026, 9, 2), eval_type='full', attempts=1)
        arm_retry(a, "llm")
        delta = a.next_retry_at - datetime.now(timezone.utc)
        assert 1.9 < delta.total_seconds() / 3600 < 2.1

    def test_cap_switches_to_needs_manual(self, session, seed_data):
        from app.services.retry_service import arm_retry, MAX_RETRY_ATTEMPTS
        a = Assessment(student_id=seed_data['s1'].id, project_id=seed_data['p1'].id,
                       date=date(2026, 9, 2), eval_type='full',
                       attempts=MAX_RETRY_ATTEMPTS)
        arm_retry(a, "repo_pull")
        assert a.status == 'needs_manual'
        assert a.next_retry_at is None

    def test_reaper_skips_needs_manual(self, session, seed_data):
        from app.services.retry_service import retry_failed_assessments
        a = Assessment(student_id=seed_data['s1'].id, project_id=seed_data['p1'].id,
                       date=date(2026, 9, 2), eval_type='full',
                       status='needs_manual', next_retry_at=None,
                       saved_context_json='{}')
        session.add(a)
        session.commit()
        assert retry_failed_assessments(session=session) == 0
