from __future__ import annotations

import json
import logging
import time
from datetime import date

from sqlmodel import Session, select

from app.models import GithubActivity, Student
from app.services.github_service import fetch_activity_for_repo
from app.services.mirror_service import extract_day_activity as _mirror_extract

SYNC_INTERVAL_SECONDS = 3.0
RATE_LIMIT_COOLDOWN_SECONDS = 45


def _is_rate_limit_error(e: Exception) -> bool:
    return "rate limit" in str(e).lower()


def _fetch_via_mirror(student, target_date: date) -> dict | None:
    try:
        local = _mirror_extract(student.github_url or student.github_repo, target_date)
    except Exception as e:
        logging.getLogger(__name__).warning(
            "镜像提取失败 student_id=%s（回退 API）: %s", getattr(student, "id", "?"), e
        )
        return None
    return {
        "commits_count": local.get("commits_count", 0),
        "commits": local.get("commits", []),
        "prs_opened": 0,
        "prs_merged": 0,
        "loc_additions": local.get("loc_additions", 0),
        "loc_deletions": local.get("loc_deletions", 0),
    }


def sync_day(target_date: date, session: Session = None, students: list = None) -> int:
    """同步指定日期学生的 GitHub 活动；students 为空则同步全部，返回成功数"""
    if session is None:
        from app.database import get_session
        session = next(get_session())

    if students is None:
        students = session.exec(select(Student)).all()
    success_count = 0

    for idx, student in enumerate(students):
        if idx > 0:
            time.sleep(SYNC_INTERVAL_SECONDS)
        existing_activity = session.exec(
            select(GithubActivity).where(
                GithubActivity.student_id == student.id,
                GithubActivity.date == target_date,
            )
        ).first()
        if existing_activity is not None and existing_activity.status == "ok":
            success_count += 1
            continue
        try:
            activity_data = _fetch_via_mirror(student, target_date)
            if activity_data is None:
                for attempt in (1, 2):
                    try:
                        activity_data = fetch_activity_for_repo(
                            repo=student.github_url or student.github_repo,
                            target_date=target_date,
                        )
                        break
                    except Exception as e:
                        if attempt == 1 and _is_rate_limit_error(e):
                            time.sleep(RATE_LIMIT_COOLDOWN_SECONDS)
                            continue
                        raise
            activity = session.exec(
                select(GithubActivity).where(
                    GithubActivity.student_id == student.id,
                    GithubActivity.date == target_date,
                )
            ).first()
            if activity is None:
                activity = GithubActivity(
                    student_id=student.id,
                    date=target_date,
                )
            activity.commits_count = activity_data.get("commits_count", 0)
            activity.commits_json = json.dumps(
                activity_data.get("commits", []), ensure_ascii=False
            )
            activity.prs_opened = activity_data.get("prs_opened", 0)
            activity.prs_merged = activity_data.get("prs_merged", 0)
            activity.loc_additions = activity_data.get("loc_additions", 0)
            activity.loc_deletions = activity_data.get("loc_deletions", 0)
            activity.status = "ok"
            activity.fetched_at = date.today()
            session.add(activity)
            success_count += 1
        except Exception as e:
            import logging
            logging.warning("GitHub 同步失败 student_id=%s: %s", student.id, e)
            activity = session.exec(
                select(GithubActivity).where(
                    GithubActivity.student_id == student.id,
                    GithubActivity.date == target_date,
                )
            ).first()
            if activity is None:
                activity = GithubActivity(
                    student_id=student.id,
                    date=target_date,
                )
            activity.status = "failed"
            activity.saved_context_json = json.dumps(
                {"student_id": student.id, "student_name": student.name, "repo": student.github_repo},
                ensure_ascii=False,
            )
            session.add(activity)

    session.commit()
    return success_count
