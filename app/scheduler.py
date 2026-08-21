from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings
from app.services.pipeline import run_today

_scheduler = None


def start_scheduler() -> "BackgroundScheduler | None":
    global _scheduler
    settings = get_settings()
    auto_run_time = getattr(settings, "auto_run_time", "").strip()
    if not auto_run_time:
        return None
    _scheduler = BackgroundScheduler(timezone=settings.tz)
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
    _scheduler.start()
    return _scheduler


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler
