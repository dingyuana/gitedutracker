import sys
import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
from sqlmodel import SQLModel, create_engine, Session, select

from app.models import EvalSchedule


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def session(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TestCreateSchedule:

    def test_persists_pending_row(self, session):
        from app.services.schedule_service import create_schedule
        run_at = _now() + timedelta(hours=3)
        sch = create_schedule(
            session, target_date=date(2026, 9, 2), run_at=run_at,
            eval_mode="full", project_id=None, only_missing=True,
            auto_send_email=False,
        )
        assert sch.id is not None
        assert sch.status == "pending"
        assert sch.eval_mode == "full"
        assert sch.only_missing is True
        assert sch.auto_send_email is False

    def test_auto_send_email_flag_persisted(self, session):
        from app.services.schedule_service import create_schedule
        sch = create_schedule(session, target_date=date(2026, 9, 2),
                              run_at=_now(), auto_send_email=True)
        assert sch.auto_send_email is True


class TestDueSchedules:

    def test_returns_only_past_pending(self, session):
        from app.services.schedule_service import create_schedule, due_schedules
        past = create_schedule(session, target_date=date(2026, 9, 2),
                               run_at=_now() - timedelta(minutes=5))
        create_schedule(session, target_date=date(2026, 9, 2),
                        run_at=_now() + timedelta(hours=2))
        ids = [s.id for s in due_schedules(session)]
        assert ids == [past.id]

    def test_excludes_non_pending(self, session):
        from app.services.schedule_service import create_schedule, due_schedules
        sch = create_schedule(session, target_date=date(2026, 9, 2),
                              run_at=_now() - timedelta(minutes=5))
        sch.status = "done"
        session.add(sch)
        session.commit()
        assert due_schedules(session) == []


class TestRunDueSchedules:

    @patch("app.services.pipeline.run_today")
    def test_passes_auto_send_email_to_pipeline(self, mock_run, session):
        from app.services.schedule_service import create_schedule, run_due_schedules
        mock_run.return_value = {"success": 3, "failed": 0}
        create_schedule(session, target_date=date(2026, 9, 2),
                        run_at=_now() - timedelta(minutes=1),
                        eval_mode="full", auto_send_email=True)

        run_due_schedules(session=session)

        assert mock_run.call_args.kwargs["send_email"] is True
        assert mock_run.call_args.kwargs["eval_mode"] == "full"

    @patch("app.services.pipeline.run_today")
    def test_defaults_to_no_email(self, mock_run, session):
        from app.services.schedule_service import create_schedule, run_due_schedules
        mock_run.return_value = {"success": 1, "failed": 0}
        create_schedule(session, target_date=date(2026, 9, 2),
                        run_at=_now() - timedelta(minutes=1))

        run_due_schedules(session=session)

        assert mock_run.call_args.kwargs["send_email"] is False

    @patch("app.services.pipeline.run_today")
    def test_marks_done_and_stores_result(self, mock_run, session):
        from app.services.schedule_service import create_schedule, run_due_schedules
        mock_run.return_value = {"success": 5, "failed": 1}
        sch = create_schedule(session, target_date=date(2026, 9, 2),
                              run_at=_now() - timedelta(minutes=1))

        summary = run_due_schedules(session=session)

        session.refresh(sch)
        assert sch.status == "done"
        assert sch.executed_at is not None
        assert '"success": 5' in sch.result_json
        assert summary["executed"] == 1

    @patch("app.services.pipeline.run_today")
    def test_failure_isolated_and_recorded(self, mock_run, session):
        from app.services.schedule_service import create_schedule, run_due_schedules
        mock_run.side_effect = [RuntimeError("boom"), {"success": 2, "failed": 0}]
        bad = create_schedule(session, target_date=date(2026, 9, 1),
                              run_at=_now() - timedelta(minutes=5))
        good = create_schedule(session, target_date=date(2026, 9, 2),
                               run_at=_now() - timedelta(minutes=4))

        summary = run_due_schedules(session=session)

        session.refresh(bad)
        session.refresh(good)
        assert bad.status == "failed"
        assert "boom" in bad.result_json
        assert good.status == "done", "单条失败不得阻断其余计划"
        assert summary["executed"] == 1
        assert summary["failed"] == 1


class TestCancelSchedule:

    def test_cancels_pending(self, session):
        from app.services.schedule_service import create_schedule, cancel_schedule
        sch = create_schedule(session, target_date=date(2026, 9, 2), run_at=_now())
        assert cancel_schedule(session, sch.id) is True
        session.refresh(sch)
        assert sch.status == "cancelled"

    def test_refuses_non_pending(self, session):
        from app.services.schedule_service import create_schedule, cancel_schedule
        sch = create_schedule(session, target_date=date(2026, 9, 2), run_at=_now())
        sch.status = "done"
        session.add(sch)
        session.commit()
        assert cancel_schedule(session, sch.id) is False


class TestSchedulerRegistersJobs:
    """缺陷 A 回归：retry_failed_assessments 曾从未被任何调度注册，导致重试永不发生。"""

    def test_registers_jobs_even_without_auto_run_time(self, monkeypatch):
        import app.scheduler as sch_mod
        monkeypatch.setattr(sch_mod, "_scheduler", None)

        from app.config import get_settings
        base = get_settings()
        monkeypatch.setattr(sch_mod, "get_settings",
                            lambda: base.model_copy(update={"auto_run_time": ""}))

        scheduler = sch_mod.start_scheduler()
        try:
            assert scheduler is not None, "无 AUTO_RUN_TIME 时仍须启动调度器"
            ids = {j.id for j in scheduler.get_jobs()}
            assert "retry_failed_assessments" in ids
            assert "run_due_schedules" in ids
            assert "run_today_daily" not in ids
        finally:
            if scheduler:
                scheduler.shutdown(wait=False)
            sch_mod._scheduler = None
