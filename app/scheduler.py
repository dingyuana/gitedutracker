from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings
from app.services.pipeline import run_today
from app.services.retry_service import retry_failed_assessments
from app.services.schedule_service import run_due_schedules

_scheduler = None


def start_scheduler() -> "BackgroundScheduler | None":
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    settings = get_settings()
    _scheduler = BackgroundScheduler(timezone=settings.tz)

    auto_run_time = getattr(settings, "auto_run_time", "").strip()
    parts = auto_run_time.split()
    if len(parts) == 5:
        minute, hour, day, month, day_of_week = parts
        _scheduler.add_job(
            run_today,
            "cron",
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            id="run_today_daily",
            replace_existing=True,
        )

    # 失败评测重试：仓库拉取失败 1h / LLM 失败 2h，由 next_retry_at 控制实际到期
    _scheduler.add_job(
        retry_failed_assessments,
        "interval",
        hours=1,
        id="retry_failed_assessments",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    _scheduler.add_job(
        run_due_schedules,
        "interval",
        minutes=1,
        id="run_due_schedules",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    _scheduler.start()
    return _scheduler


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler
