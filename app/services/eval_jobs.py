from __future__ import annotations

import threading
import uuid
import logging
from datetime import date

from app.database import get_session
from app.services.pipeline import run_today

_jobs: dict = {}
_lock = threading.Lock()


def start_eval_job(
    target_date: date,
    project_id: int,
    only_missing: bool = False,
    eval_mode: str = "diff",
    plan_id: int | None = None,
    sample_size: int | None = None,
) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "project_id": project_id,
            "date": str(target_date),
            "eval_mode": eval_mode,
            "plan_id": plan_id,
            "status": "syncing",
            "done": 0,
            "total": 0,
            "current": "",
            "started_at": datetime_now(),
        }

    def progress_cb(done: int, total: int, current: str):
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job["status"] = "scoring"
                job["done"] = done
                job["total"] = total
                job["current"] = current

    def worker():
        session = next(get_session())
        try:
            result = run_today(
                target_date,
                session=session,
                only_missing=only_missing,
                eval_mode=eval_mode,
                project_id=project_id,
                plan_id=plan_id,
                sample_size=sample_size,
                progress_cb=progress_cb,
            )
            with _lock:
                job = _jobs.get(job_id)
                if job is not None:
                    job["status"] = "finished"
                    job["result"] = result
        except Exception as e:
            logging.getLogger(__name__).exception("评测任务失败 job=%s", job_id)
            with _lock:
                job = _jobs.get(job_id)
                if job is not None:
                    job["status"] = "error"
                    job["error"] = str(e)
        finally:
            session.close()

    threading.Thread(target=worker, daemon=True).start()
    return job_id


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def is_running() -> bool:
    """是否有评测任务正在进行（syncing/scoring 中）。"""
    with _lock:
        return any(
            job.get("status") in ("syncing", "scoring")
            for job in _jobs.values()
        )


def running_job_id() -> str | None:
    """返回当前正在进行的评测 job_id，无则返回 None。"""
    with _lock:
        for jid, job in _jobs.items():
            if job.get("status") in ("syncing", "scoring"):
                return jid
    return None


def datetime_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
