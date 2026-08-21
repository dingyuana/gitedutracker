from __future__ import annotations

import io
from datetime import date
from typing import Optional

import pandas as pd
from sqlmodel import Session, select

from app.database import engine
from app.models import Assessment, GithubActivity, Project, Student


def export_daily(target_date: date, session: Optional[Session] = None) -> bytes:
    """导出指定日期的评分表为 xlsx bytes"""
    if session is None:
        session = Session(engine)

    stmt = (
        select(
            Assessment.date,
            Student.name,
            Student.email,
            Student.github_repo,
            Project.name,
            GithubActivity.loc_additions,
            GithubActivity.loc_deletions,
            Assessment.quality_score,
            Assessment.match_score,
            Assessment.schedule_status,
            Assessment.total_score,
            Assessment.comment,
        )
        .join(Student, Assessment.student_id == Student.id)
        .join(Project, Assessment.project_id == Project.id)
        .join(
            GithubActivity,
            (GithubActivity.student_id == Assessment.student_id)
            & (GithubActivity.date == Assessment.date),
        )
        .where(Assessment.date == target_date)
        .where(Assessment.status == 'done')
    )
    rows = session.exec(stmt).all()

    columns = [
        '日期', '学生姓名', '邮箱', 'GitHub仓库', '项目名称',
        '代码增', '代码删', '质量分', '匹配分', '进度', '总分', '评语',
    ]
    df = pd.DataFrame(rows, columns=columns)
    df['日期'] = df['日期'].astype(str)

    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine='openpyxl')
    return buf.getvalue()
