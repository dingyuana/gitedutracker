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


def export_project_assessments(project_id: int, session: Optional[Session] = None) -> bytes:
    """导出指定项目全部评测记录为多 sheet xlsx bytes。

    Sheet1「分数总览」：学生(行) × 日期(列) 总分矩阵 + 每行学生平均分列 + 「每日平均」行。
    其余每个日期一个 sheet：当日各学生 质量分/匹配分/进度/总分/评语。
    仅导出 status == 'done' 的记录。
    """
    if session is None:
        session = Session(engine)

    rows = session.exec(
        select(
            Assessment.date,
            Student.name,
            Assessment.total_score,
            Assessment.quality_score,
            Assessment.match_score,
            Assessment.schedule_status,
            Assessment.comment,
        )
        .join(Student, Assessment.student_id == Student.id)
        .where(Assessment.project_id == project_id)
        .where(Assessment.status == 'done')
    ).all()

    buf = io.BytesIO()
    if not rows:
        empty = pd.DataFrame(columns=['学生姓名', '平均分'])
        empty.to_excel(buf, index=False, sheet_name='分数总览', engine='openpyxl')
        return buf.getvalue()

    df = pd.DataFrame(rows, columns=[
        '日期', '学生姓名', '总分', '质量分', '匹配分', '进度', '评语',
    ])

    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        overview = df.pivot_table(index='学生姓名', columns='日期',
                                  values='总分', aggfunc='first')
        overview.columns = [str(c) for c in overview.columns]
        overview['平均分'] = overview.mean(axis=1)
        overview.loc['每日平均'] = overview.mean(axis=0)
        overview.to_excel(writer, sheet_name='分数总览')

        daily_cols = ['学生姓名', '质量分', '匹配分', '进度', '总分', '评语']
        for d in sorted(df['日期'].unique()):
            day = df[df['日期'] == d][daily_cols]
            day.to_excel(writer, sheet_name=str(d), index=False)

    return buf.getvalue()
