from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.models import EvalSchedule

logger = logging.getLogger(__name__)


def _naive_utc_now() -> datetime:
    # SQLite 存的是 naive datetime，比较前必须去掉 tzinfo 否则 TypeError
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_schedule(
    session: Session,
    target_date: date,
    run_at: datetime,
    eval_mode: str = "diff",
    project_id: Optional[int] = None,
    plan_id: Optional[int] = None,
    only_missing: bool = True,
    sample_size: Optional[int] = None,
    auto_send_email: bool = False,
) -> EvalSchedule:
    if run_at.tzinfo is not None:
        run_at = run_at.astimezone(timezone.utc).replace(tzinfo=None)

    schedule = EvalSchedule(
        target_date=target_date,
        run_at=run_at,
        eval_mode=eval_mode,
        project_id=project_id,
        plan_id=plan_id,
        only_missing=only_missing,
        sample_size=sample_size,
        auto_send_email=auto_send_email,
        status="pending",
    )
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    return schedule


def due_schedules(session: Session, now: Optional[datetime] = None) -> list[EvalSchedule]:
    cutoff = now or _naive_utc_now()
    if cutoff.tzinfo is not None:
        cutoff = cutoff.astimezone(timezone.utc).replace(tzinfo=None)
    return list(session.exec(
        select(EvalSchedule)
        .where(EvalSchedule.status == "pending", EvalSchedule.run_at <= cutoff)
        .order_by(EvalSchedule.run_at)
    ).all())


def cancel_schedule(session: Session, schedule_id: int) -> bool:
    schedule = session.get(EvalSchedule, schedule_id)
    if schedule is None or schedule.status != "pending":
        return False
    schedule.status = "cancelled"
    session.add(schedule)
    session.commit()
    return True


def run_due_schedules(session: Optional[Session] = None,
                      now: Optional[datetime] = None) -> dict:
    if session is None:
        from app.database import get_session
        session = next(get_session())

    from app.services.pipeline import run_today

    executed = 0
    failed = 0

    for schedule in due_schedules(session, now):
        schedule.status = "running"
        session.add(schedule)
        session.commit()

        try:
            result = run_today(
                schedule.target_date,
                session=session,
                only_missing=schedule.only_missing,
                eval_mode=schedule.eval_mode,
                project_id=schedule.project_id,
                plan_id=schedule.plan_id,
                sample_size=schedule.sample_size,
                send_email=schedule.auto_send_email,
            )
            schedule.status = "done"
            schedule.result_json = json.dumps(result, ensure_ascii=False, default=str)
            executed += 1
        except Exception as e:
            logger.warning("定时评测计划执行失败 schedule_id=%s: %s", schedule.id, e)
            schedule.status = "failed"
            schedule.result_json = json.dumps(
                {"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False
            )
            failed += 1

        schedule.executed_at = _naive_utc_now()
        session.add(schedule)
        session.commit()

    return {"executed": executed, "failed": failed}
