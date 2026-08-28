from __future__ import annotations

import logging
import smtplib
from datetime import date
from email.mime.text import MIMEText
from typing import Optional

from sqlmodel import Session, select

from app.models import Assessment, Project, Student
from app.services.settings_service import get_effective_settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


def _build_email(student: Student, assessments: list[Assessment],
                 project_names: Optional[dict[int, str]] = None) -> tuple[str, str]:
    """Build subject and HTML body for a student's daily email (comments only, no scores)."""
    date_str = assessments[0].date.isoformat()
    subject = f"GitHub 日报 - {date_str}"

    comments = [a.comment for a in assessments if a.comment]
    if comments:
        comment_blocks = "".join(
            f'<blockquote style="margin:0.5rem 0;padding:0.75rem 1rem;'
            f'border-left:4px solid #4caf50;background:#f7faf7;color:#333;">'
            f'{c}</blockquote>'
            for c in comments
        )
    else:
        comment_blocks = '<p>今日暂无详细评语，请继续努力！</p>'

    body = f"""\
<html>
<body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;line-height:1.7;color:#222;max-width:600px;margin:0 auto;">
<h2 style="color:#2e7d32;">🌱 {date_str} GitHub 学习日报</h2>
{comment_blocks}
<hr style="border:none;border-top:1px solid #eee;">
<p style="color:#666;">无论进展如何，持续学习和动手实践本身就是最重要的。如果遇到什么困难，随时可以联系老师或同学交流，我们一起想办法解决！继续加油！🚀</p>
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

    settings = get_effective_settings(session)

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
