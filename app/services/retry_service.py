from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from openai import APIError, RateLimitError
from sqlmodel import Session, select

from app.models import Assessment, ScoringConfig
from app.services.ai_scoring_service import LLMInvalidResponse, score_student
from app.services.scoring_engine import compute_final


def _attempt_score(
    student_id: int,
    context: str,
    session: Session,
    settings,
    target_date: Optional[date] = None,
) -> bool:
    """尝试一次评分，含 3 次重试（指数退避 1s, 2s）。

    成功  → 更新 Assessment(status='done') 并返回 True
    3 次均失败 → Assessment(status='failed', next_retry_at=now+2h, saved_context_json=context) 并返回 False
    """
    max_attempts = 3
    ctx_dict = json.loads(context) if isinstance(context, str) else context

    for attempt in range(1, max_attempts + 1):
        try:
            subscores = score_student(ctx_dict, settings)

            config = session.exec(select(ScoringConfig)).first()
            if config is None:
                from app.models import ScoringConfig as _DefaultConfig
                config = _DefaultConfig()

            subscores["loc"] = ctx_dict.get("loc_additions", 0) + ctx_dict.get("loc_deletions", 0)
            total_score = compute_final(subscores, config)

            query_date = target_date or ctx_dict.get("date")
            proj_id = ctx_dict.get("project_id")
            q = select(Assessment).where(
                Assessment.student_id == student_id,
                Assessment.date == query_date,
            )
            if proj_id is not None:
                q = q.where(Assessment.project_id == proj_id)
            assessment = session.exec(q).first()
            if assessment is None:
                return False

            assessment.status = "done"
            assessment.quality_score = subscores.get("quality_score")
            assessment.match_score = subscores.get("match_score")
            assessment.schedule_status = subscores.get("schedule_status", "ontime")
            assessment.total_score = total_score
            assessment.comment = subscores.get("comment", "")
            assessment.evaluated_at = datetime.now(timezone.utc)
            assessment.saved_context_json = context

            session.commit()
            return True

        except Exception as e:
            if attempt == max_attempts:
                query_date = target_date or ctx_dict.get("date")
                proj_id = ctx_dict.get("project_id")
                q = select(Assessment).where(
                    Assessment.student_id == student_id,
                    Assessment.date == query_date,
                )
                if proj_id is not None:
                    q = q.where(Assessment.project_id == proj_id)
                assessment = session.exec(q).first()
                if assessment is None:
                    return False

                assessment.status = "failed"
                assessment.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=2)
                assessment.saved_context_json = context
                session.commit()
                return False
            time.sleep(2 ** (attempt - 1))

    return False


def retry_failed_assessments(session: Optional[Session] = None) -> int:
    """查询所有 status='failed' 且 next_retry_at <= now 的 Assessment，逐一调用 _attempt_score 重试。

    返回成功重试的条数。
    """
    if session is None:
        from app.database import get_session
        session = next(get_session())

    from app.config import get_settings
    settings = get_settings()

    now = datetime.now(timezone.utc)

    assessments = session.exec(
        select(Assessment).where(
            Assessment.status == "failed",
            Assessment.next_retry_at.isnot(None),
            Assessment.next_retry_at <= now,
        )
    ).all()

    success_count = 0
    for assessment in assessments:
        if assessment.saved_context_json is None:
            continue

        ok = _attempt_score(
            assessment.student_id,
            assessment.saved_context_json,
            session,
            settings,
            target_date=assessment.date,
        )
        if ok:
            success_count += 1

    return len(assessments)
