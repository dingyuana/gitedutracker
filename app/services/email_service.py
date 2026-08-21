from __future__ import annotations

import logging
import smtplib
from datetime import date
from email.mime.text import MIMEText
from typing import Optional

from sqlmodel import Session, select

from app.config import get_settings
from app.models import Assessment, Project, Student

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


def _build_email(student: Student, assessments: list[Assessment],
                 project_names: Optional[dict[int, str]] = None) -> tuple[str, str]:
    """Build subject and HTML body for a student's daily email."""
    date_str = assessments[0].date.isoformat()
    subject = f"GitHub 日报 - {date_str}"

    comments = [a.comment for a in assessments if a.comment]
    if comments:
        comment_text = "\n".join(comments)
    else:
        comment_text = "今日暂无详细评语，请继续努力！"

    proj_map = project_names or {}

    if len(assessments) == 1:
        a = assessments[0]
        pname = proj_map.get(a.project_id, f"项目{a.project_id}")
        score_row = f'<tr><td>{pname}</td><td>{a.total_score:.1f}</td><td>{a.quality_score if a.quality_score is not None else "N/A"}</td><td>{a.match_score if a.match_score is not None else "N/A"}</td></tr>'
        score_table = f"""\
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;max-width:600px;font-size:14px;">
<thead><tr style="background:#f0f0f0;">
<th style="text-align:left;">项目</th>
<th style="text-align:center;">总分</th>
<th style="text-align:center;">代码质量</th>
<th style="text-align:center;">任务匹配</th>
</tr></thead>
<tbody>{score_row}</tbody>
</table>"""
        summary = f'<p>总分：<strong>{assessments[0].total_score:.1f}</strong></p>'
    else:
        rows = []
        for a in assessments:
            pname = proj_map.get(a.project_id, f"项目{a.project_id}")
            rows.append(
                f'<tr>'
                f'<td>{pname}</td>'
                f'<td style="text-align:center;">{a.total_score:.1f}</td>'
                f'<td style="text-align:center;">{a.quality_score if a.quality_score is not None else "N/A"}</td>'
                f'<td style="text-align:center;">{a.match_score if a.match_score is not None else "N/A"}</td>'
                f'</tr>'
            )
        score_table = f"""\
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;max-width:600px;font-size:14px;">
<thead><tr style="background:#f0f0f0;">
<th style="text-align:left;">项目</th>
<th style="text-align:center;">总分</th>
<th style="text-align:center;">代码质量</th>
<th style="text-align:center;">任务匹配</th>
</tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>"""
        avg_score = sum(a.total_score or 0 for a in assessments) / len(assessments)
        summary = f'<p>平均分：<strong>{avg_score:.1f}</strong>（{len(assessments)} 个项目）</p>'

    body = f"""\
<html>
<body>
<h2>🌱 {date_str} GitHub 学习日报</h2>
<p>{comment_text}</p>
<hr>
{score_table}
<hr>
{summary}
<p>继续加油！🚀</p>
</body>
</html>
"""
    return subject, body


def _send_one(smtp_host: str, smtp_port: int, smtp_user: str, smtp_pass: str,
              smtp_from: str, to: str, subject: str, body: str) -> bool:
    """Send a single email with retry logic. Returns True on success."""
    msg = MIMEText(body, 'html', 'utf-8')
    msg['Subject'] = subject
    msg['From'] = smtp_from
    msg['To'] = to

    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, [to], msg.as_string())
            return True
        except Exception as exc:
            last_error = exc
            logger.warning("SMTP send failed (attempt %d/%d) to %s: %s",
                           attempt, MAX_RETRIES, to, exc)
            if attempt < MAX_RETRIES:
                import time
                time.sleep(RETRY_DELAY_SECONDS)
    return False


def send_daily_comments(target_date: date, session: Optional[Session] = None) -> dict:
    """Send daily summary emails to all students with done assessments that haven't been emailed.

    Queries: Assessment.status='done' AND email_sent=false, JOIN Student for email.
    Groups by student — one email per student per day (D25).
    Marks email_sent=true after successful send.

    Returns:
        {"sent": int, "skipped": int, "failed": int}
    """
    if session is None:
        from app.database import get_session
        session = next(get_session())

    settings = get_settings()

    # Query done assessments not yet emailed, joined with Student
    results = session.exec(
        select(Assessment, Student)
        .join(Student, Assessment.student_id == Student.id)
        .where(
            Assessment.status == 'done',
            Assessment.email_sent == False,
            Assessment.date == target_date,
        )
    ).all()

    from collections import defaultdict
    student_assessments: dict[int, tuple[Student, list[Assessment]]] = defaultdict(list)
    all_project_ids: set[int] = set()
    for assessment, student in results:
        student_assessments[student.id].append((student, assessment))
        all_project_ids.add(assessment.project_id)

    project_names: dict[int, str] = {
        p.id: p.name
        for p in session.exec(select(Project).where(Project.id.in_(all_project_ids))).all()
    }

    sent = 0
    skipped = 0
    failed = 0

    for student_id, entries in student_assessments.items():
        student = entries[0][0]
        assessments = [e[1] for e in entries]

        if not student.email:
            skipped += 1
            continue

        subject, body = _build_email(student, assessments, project_names=project_names)

        success = _send_one(
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_user=settings.smtp_user,
            smtp_pass=settings.smtp_pass,
            smtp_from=settings.smtp_from,
            to=student.email,
            subject=subject,
            body=body,
        )

        if success:
            for a in assessments:
                a.email_sent = True
            sent += 1
        else:
            failed += 1

    session.commit()

    return {
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }
