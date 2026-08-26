import sys
import os
import json
import pytest
from datetime import date, datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlmodel import SQLModel, create_engine, Session, select
from app.models import (
    Student, Project, DailyPlan, GithubActivity, Assessment, ScoringConfig,
)


@pytest.fixture(autouse=True)
def _no_network_code_extract(request):
    from unittest.mock import patch as _patch
    if request.node.get_closest_marker("real_mirror"):
        yield
        return
    with _patch("app.services.pipeline.extract_day_activity",
                return_value={"commits_count": 0, "loc_additions": 0,
                              "loc_deletions": 0, "code_diffs": []}), \
         _patch("app.services.pipeline.extract_snapshot",
                return_value={"files": []}):
        yield


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

    s1.project_id = p1.id
    s2.project_id = p1.id
    session.add(s1)
    session.add(s2)
    session.commit()

    plan_all = DailyPlan(
        project_id=p1.id,
        date=date(2026, 8, 21),
        content='完成登录模块',
        student_id=None,
    )
    plan_s1 = DailyPlan(
        project_id=p1.id,
        date=date(2026, 8, 21),
        content='完成登录模块（张三专属）',
        student_id=s1.id,
    )
    session.add_all([plan_all, plan_s1])
    session.commit()
    session.refresh(plan_all)
    session.refresh(plan_s1)

    config = ScoringConfig(
        w_volume=0.333, w_quality=0.333, w_match=0.333,
        loc_threshold=100, schedule_bonus=5.0, schedule_penalty=-5.0,
    )
    session.add(config)
    session.commit()
    session.refresh(config)

    # Seed GithubActivity records with status="ok" so run_today has data to score
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
        'plan_all': plan_all, 'plan_s1': plan_s1, 'config': config,
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
        "comment": "表现良好",
        "reasoning": "按时完成",
    }


class TestRunTodaySuccess:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_generates_done_assessments(self, mock_sync_day, mock_score_student, mock_send_daily,
                                        session, seed_data, mock_settings, mock_ai_response):
        from app.services.pipeline import run_today

        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response
        mock_send_daily.return_value = None

        result = run_today(seed_data['target'], session=session)

        assert result["success"] >= 1
        assert result["failed"] == 0
        assert isinstance(result["details"], list)

        assessments = session.exec(
            select(Assessment).where(Assessment.date == seed_data['target'])
        ).all()
        assert len(assessments) >= 1
        for a in assessments:
            assert a.status == "done"
            assert a.total_score is not None
            assert a.quality_score is not None
            assert a.evaluated_at is not None

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_returns_correct_counts(self, mock_sync_day, mock_score_student, mock_send_daily,
                                    session, seed_data, mock_settings, mock_ai_response):
        from app.services.pipeline import run_today

        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response
        mock_send_daily.return_value = None

        result = run_today(seed_data['target'], session=session)

        assert isinstance(result["success"], int)
        assert isinstance(result["failed"], int)
        assert result["success"] + result["failed"] == len(result["details"])


class TestLLMFailureIsolation:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_one_student_failure_does_not_affect_others(self, mock_sync_day, mock_score_student, mock_send_daily,
                                                        session, seed_data, mock_settings, mock_ai_response):
        from app.services.pipeline import run_today
        from app.services.ai_scoring_service import LLMInvalidResponse

        mock_sync_day.return_value = 2

        def side_effect(context, settings):
            student_id = context.get('student_id')
            if student_id == seed_data['s2'].id:
                raise LLMInvalidResponse("LLM failed")
            return mock_ai_response

        mock_score_student.side_effect = side_effect

        result = run_today(seed_data['target'], session=session)

        assert result["failed"] >= 1
        assert result["success"] >= 1

        s1_assessments = session.exec(
            select(Assessment).where(
                Assessment.student_id == seed_data['s1'].id,
                Assessment.date == seed_data['target'],
            )
        ).all()
        for a in s1_assessments:
            assert a.status == "done"

        s2_assessments = session.exec(
            select(Assessment).where(
                Assessment.student_id == seed_data['s2'].id,
                Assessment.date == seed_data['target'],
            )
        ).all()
        for a in s2_assessments:
            assert a.status == "failed"
            assert a.next_retry_at is not None
            assert a.saved_context_json is not None

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_failed_assessment_has_retry_fields(self, mock_sync_day, mock_score_student, mock_send_daily,
                                                 session, seed_data, mock_settings):
        from app.services.pipeline import run_today
        from app.services.ai_scoring_service import LLMInvalidResponse

        mock_sync_day.return_value = 2
        mock_score_student.side_effect = LLMInvalidResponse("boom")

        result = run_today(seed_data['target'], session=session)

        assert result["failed"] >= 1
        assert result["success"] == 0

        assessments = session.exec(
            select(Assessment).where(Assessment.date == seed_data['target'])
        ).all()
        for a in assessments:
            assert a.status == "failed"
            assert a.attempts >= 1
            assert a.next_retry_at is not None
            assert a.saved_context_json is not None


class TestIdempotency:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_repeated_call_does_not_duplicate_assessments(self, mock_sync_day, mock_score_student, mock_send_daily,
                                                          session, seed_data, mock_settings, mock_ai_response):
        from app.services.pipeline import run_today

        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response

        run_today(seed_data['target'], session=session)
        first_count = len(session.exec(
            select(Assessment).where(Assessment.date == seed_data['target'])
        ).all())

        run_today(seed_data['target'], session=session)
        second_count = len(session.exec(
            select(Assessment).where(Assessment.date == seed_data['target'])
        ).all())

        assert first_count == second_count

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_repeated_call_updates_existing_assessment(self, mock_sync_day, mock_score_student, mock_send_daily,
                                                       session, seed_data, mock_settings, mock_ai_response):
        from app.services.pipeline import run_today

        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response

        run_today(seed_data['target'], session=session)

        first_evaluated = session.exec(
            select(Assessment).where(
                Assessment.student_id == seed_data['s1'].id,
                Assessment.date == seed_data['target'],
            )
        ).first()
        first_total = first_evaluated.total_score

        mock_score_student.return_value = {
            **mock_ai_response,
            "quality_score": 95,
            "match_score": 95,
        }

        run_today(seed_data['target'], session=session)

        updated = session.exec(
            select(Assessment).where(
                Assessment.student_id == seed_data['s1'].id,
                Assessment.date == seed_data['target'],
            )
        ).first()
        assert updated.id == first_evaluated.id
        assert updated.quality_score == 95
        assert updated.match_score == 95
        assert updated.status == "done"


class TestPlanFiltering:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_student_specific_plan_only_applies_to_that_student(self, mock_sync_day, mock_score_student, mock_send_daily,
                                                                 session, seed_data, mock_settings, mock_ai_response):
        from app.services.pipeline import run_today

        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response

        result = run_today(seed_data['target'], session=session)

        s2_assessments = session.exec(
            select(Assessment).where(
                Assessment.student_id == seed_data['s2'].id,
                Assessment.date == seed_data['target'],
            )
        ).all()
        # s2 should not have an assessment tied to the student-specific plan (plan_s1)
        # plan_s1 only applies to s1, so s2 should only have assessments from plan_all
        s2_project_ids = {a.project_id for a in s2_assessments}
        # If s2 has any assessments, they should all be from the all-students plan
        for a in s2_assessments:
            assert a.saved_context_json is None or '张三专属' not in (a.saved_context_json or '')

        s1_assessments = session.exec(
            select(Assessment).where(
                Assessment.student_id == seed_data['s1'].id,
                Assessment.date == seed_data['target'],
            )
        ).all()
        assert len(s1_assessments) >= 1


class TestContextConstruction:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_passes_correct_context_to_score_student(self, mock_sync_day, mock_score_student, mock_send_daily,
                                                      session, seed_data, mock_settings, mock_ai_response):
        from app.services.pipeline import run_today

        mock_sync_day.return_value = 2

        def capture(context, settings):
            assert "plan_content" in context
            assert "commits" in context
            assert "prs_opened" in context
            assert "prs_merged" in context
            assert "loc_additions" in context
            assert "loc_deletions" in context
            return mock_ai_response

        mock_score_student.side_effect = capture

        run_today(seed_data['target'], session=session)


class TestReturnStructure:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_returns_dict_with_required_keys(self, mock_sync_day, mock_score_student, mock_send_daily,
                                              session, seed_data, mock_settings, mock_ai_response):
        from app.services.pipeline import run_today

        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response

        result = run_today(seed_data['target'], session=session)

        assert "success" in result
        assert "failed" in result
        assert "details" in result
        assert isinstance(result["success"], int)
        assert isinstance(result["failed"], int)
        assert isinstance(result["details"], list)


class TestProjectScoping:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_students_only_scored_within_own_project(self, mock_sync_day, mock_score_student,
                                                     mock_send_daily, session, mock_settings, mock_ai_response):
        from app.services.pipeline import run_today
        target = date(2026, 8, 21)
        p1 = Project(name='项目一')
        p2 = Project(name='项目二')
        session.add_all([p1, p2])
        session.commit()
        session.refresh(p1)
        session.refresh(p2)

        sa = Student(name='甲', email='a@x.com', github_repo='a/repo', project_id=p1.id)
        sb = Student(name='乙', email='b@x.com', github_repo='b/repo', project_id=p2.id)
        sc = Student(name='丙', email='c@x.com', github_repo='c/repo')
        session.add_all([sa, sb, sc])
        session.commit()
        for s in [sa, sb, sc]:
            session.refresh(s)

        session.add(DailyPlan(project_id=p1.id, date=target, content='任务一', student_id=None))
        session.add(DailyPlan(project_id=p2.id, date=target, content='任务二', student_id=None))
        session.add(ScoringConfig())
        for s in [sa, sb, sc]:
            session.add(GithubActivity(student_id=s.id, date=target, commits_count=1, status="ok"))
        session.commit()

        mock_sync_day.return_value = 3
        mock_score_student.return_value = mock_ai_response
        mock_send_daily.return_value = None

        result = run_today(target, session=session)

        assessments = session.exec(select(Assessment).where(Assessment.date == target)).all()
        pairs = {(a.student_id, a.project_id) for a in assessments}
        assert pairs == {(sa.id, p1.id), (sb.id, p2.id)}
        assert result["success"] == 2


class TestOnlyMissingScope:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_only_missing_skips_done_assessments(self, mock_sync_day, mock_score_student,
                                                 mock_send_daily, session, seed_data,
                                                 mock_settings, mock_ai_response):
        from app.services.pipeline import run_today
        target = seed_data['target']
        session.add(Assessment(
            student_id=seed_data['s1'].id,
            project_id=seed_data['p1'].id,
            date=target,
            status="done",
            total_score=77,
        ))
        session.commit()
        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response
        mock_send_daily.return_value = None

        result = run_today(target, session=session, only_missing=True)

        assert mock_score_student.call_count == 1
        done_pairs = {
            (a.student_id, a.project_id)
            for a in session.exec(select(Assessment).where(Assessment.date == target)).all()
            if a.status == "done"
        }
        assert (seed_data['s1'].id, seed_data['p1'].id) in done_pairs
        assert result["success"] == 1

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_only_missing_retries_failed(self, mock_sync_day, mock_score_student,
                                         mock_send_daily, session, seed_data,
                                         mock_settings, mock_ai_response):
        from app.services.pipeline import run_today
        target = seed_data['target']
        session.add(Assessment(
            student_id=seed_data['s1'].id,
            project_id=seed_data['p1'].id,
            date=target,
            status="failed",
            attempts=1,
        ))
        session.commit()
        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response
        mock_send_daily.return_value = None

        run_today(target, session=session, only_missing=True)

        assert mock_score_student.call_count == 3


class TestEvalModes:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.extract_day_activity")
    def test_diff_mode_passes_code_diffs(self, mock_extract, mock_sync_day, mock_score_student,
                                         mock_send_daily, session, seed_data,
                                         mock_settings, mock_ai_response):
        from app.services.pipeline import run_today
        mock_extract.return_value = {
            "commits_count": 1, "loc_additions": 10, "loc_deletions": 2,
            "code_diffs": [{"sha": "abc", "message": "m", "patch": "+print(1)"}],
        }
        mock_sync_day.return_value = 1
        mock_score_student.return_value = mock_ai_response
        mock_send_daily.return_value = None

        run_today(seed_data['target'], session=session)

        ctx = mock_score_student.call_args[0][0]
        assert ctx.get("code_diffs")[0]["patch"] == "+print(1)"

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.extract_snapshot")
    def test_full_mode_passes_project_files(self, mock_snap, mock_sync_day, mock_score_student,
                                            mock_send_daily, session, seed_data,
                                            mock_settings, mock_ai_response):
        from app.services.pipeline import run_today
        mock_snap.return_value = {"files": [{"path": "main.py", "content": "print(1)", "truncated": False}]}
        mock_sync_day.return_value = 1
        mock_score_student.return_value = mock_ai_response
        mock_send_daily.return_value = None

        run_today(seed_data['target'], session=session, eval_mode="full")

        ctx = mock_score_student.call_args[0][0]
        assert ctx.get("project_files")[0]["path"] == "main.py"

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.extract_day_activity")
    def test_extract_failure_degrades_gracefully(self, mock_extract, mock_sync_day, mock_score_student,
                                                 mock_send_daily, session, seed_data,
                                                 mock_settings, mock_ai_response):
        from app.services.pipeline import run_today
        mock_extract.side_effect = RuntimeError("git boom")
        mock_sync_day.return_value = 1
        mock_score_student.return_value = mock_ai_response
        mock_send_daily.return_value = None

        result = run_today(seed_data['target'], session=session)

        ctx = mock_score_student.call_args[0][0]
        assert ctx.get("code_diffs") == []
        assert result["success"] >= 1


class TestProjectScopedRun:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_project_id_filters_pairs(self, mock_sync_day, mock_score_student,
                                      mock_send_daily, session, mock_settings, mock_ai_response):
        from app.services.pipeline import run_today
        target = date(2026, 8, 21)
        p1 = Project(name='项目一'); p2 = Project(name='项目二')
        session.add_all([p1, p2]); session.commit(); session.refresh(p1); session.refresh(p2)

        sa = Student(name='甲', email='pa@x.com', github_repo='a/r', project_id=p1.id)
        sb = Student(name='乙', email='pb@x.com', github_repo='b/r', project_id=p2.id)
        session.add_all([sa, sb]); session.commit()
        for s_ in [sa, sb]:
            session.refresh(s_)
        session.add(DailyPlan(project_id=p1.id, date=target, content='任务一', student_id=None))
        session.add(DailyPlan(project_id=p2.id, date=target, content='任务二', student_id=None))
        session.add(ScoringConfig())
        for s_ in [sa, sb]:
            session.add(GithubActivity(student_id=s_.id, date=target, commits_count=1, status="ok"))
        session.commit()

        mock_sync_day.return_value = 1
        mock_score_student.return_value = mock_ai_response
        mock_send_daily.return_value = None

        result = run_today(target, session=session, project_id=p1.id)

        assert result["success"] == 1
        pairs = {(a.student_id, a.project_id) for a in
                 session.exec(select(Assessment).where(Assessment.date == target)).all()}
        assert pairs == {(sa.id, p1.id)}

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    def test_progress_callback_reports(self, mock_sync_day, mock_score_student,
                                       mock_send_daily, session, seed_data,
                                       mock_settings, mock_ai_response):
        from app.services.pipeline import run_today
        events = []

        def cb(done, total, current):
            events.append((done, total, current))

        mock_sync_day.return_value = 2
        mock_score_student.return_value = mock_ai_response
        mock_send_daily.return_value = None

        run_today(seed_data['target'], session=session, progress_cb=cb)

        assert events[0] == (0, 3, "")
        scoring_events = [e for e in events if e[0] > 0]
        assert len(scoring_events) == 3
        dones = [e[0] for e in scoring_events]
        assert dones == sorted(dones)
        assert events[-1][0] == events[-1][1] == 3
        assert all(isinstance(e[2], str) and e[2] for e in scoring_events)
