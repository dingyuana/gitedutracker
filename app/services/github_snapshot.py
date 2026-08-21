from __future__ import annotations

import json
from datetime import date
from typing import Optional

from sqlmodel import Session, select

from app.models import GithubActivity, Student
from app.services.github_service import fetch_activity


def sync_day(target_date: date, session: Session = None) -> int:
    """同步指定日期所有学生的 GitHub 活动，返回成功数"""
    if session is None:
        from app.database import get_session
        session = next(get_session())

    students = session.exec(select(Student)).all()
    success_count = 0

    for student in students:
        try:
            activity_data = fetch_activity(
                repo=student.github_repo,
                date=target_date,
            )
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
