from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from openai import APIError, RateLimitError
from sqlmodel import Session, select

from app.models import Assessment, ScoringConfig
from app.services.ai_scoring_service import LLMInvalidResponse, score_student
from app.services.scoring_engine import (
    compute_final, derive_schedule_adjustment, derive_volume_score,
)
from app.services.settings_service import get_effective_settings


RETRY_DELAY_REPO_PULL_HOURS = 1
RETRY_DELAY_LLM_HOURS = 2
MAX_RETRY_ATTEMPTS = 5


def _find_assessment(session: Session, student_id: int, ctx_dict: dict,
                     eval_type: str, target_date: Optional[date]):
    q = select(Assessment).where(
        Assessment.student_id == student_id,
        Assessment.date == (target_date or ctx_dict.get("date")),
        Assessment.eval_type == eval_type,
    )
    proj_id = ctx_dict.get("project_id")
    if proj_id is not None:
        q = q.where(Assessment.project_id == proj_id)
    return session.exec(q).first()


def arm_retry(assessment: Assessment, reason: str) -> None:
    """按失败原因安排下次重试；超过上限则转人工处理，避免无效仓库被无限重试。"""
    assessment.fail_reason = reason
    if assessment.attempts >= MAX_RETRY_ATTEMPTS:
        assessment.status = "needs_manual"
        assessment.next_retry_at = None
        return
    hours = (RETRY_DELAY_REPO_PULL_HOURS if reason == "repo_pull"
             else RETRY_DELAY_LLM_HOURS)
    assessment.status = "failed"
    assessment.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=hours)


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
    eval_type = ctx_dict.get("eval_mode") or "diff"

    for attempt in range(1, max_attempts + 1):
        try:
            subscores = score_student(ctx_dict, settings)

            config = session.exec(select(ScoringConfig)).first()
            if config is None:
                from app.models import ScoringConfig as _DefaultConfig
                config = _DefaultConfig()

            subscores["loc"] = ctx_dict.get("loc_additions", 0) + ctx_dict.get("loc_deletions", 0)
            engine_input = {
                "loc": subscores["loc"],
                "volume": subscores.get("volume"),
                "quality": subscores.get("quality_score", 0),
                "match": subscores.get("match_score", 0),
                "schedule_status": subscores.get("schedule_status", "ontime"),
                "bonus": subscores.get("bonus", 0),
            }
            total_score = compute_final(engine_input, config)

            assessment = _find_assessment(session, student_id, ctx_dict, eval_type, target_date)
            if assessment is None:
                return False

            assessment.status = "done"
            assessment.quality_score = subscores.get("quality_score")
            assessment.match_score = subscores.get("match_score")
            assessment.volume_score = derive_volume_score(engine_input, config)
            assessment.schedule_status = subscores.get("schedule_status", "ontime")
            assessment.schedule_adjustment = derive_schedule_adjustment(engine_input, config)
            assessment.total_score = total_score
            assessment.bonus_score = subscores.get("bonus")
            assessment.comment = subscores.get("comment", "")
            assessment.attempts += 1
            assessment.evaluated_at = datetime.now(timezone.utc)
            assessment.saved_context_json = context

            session.commit()
            return True

        except Exception as e:
            if attempt == max_attempts:
                assessment = _find_assessment(session, student_id, ctx_dict, eval_type, target_date)
                if assessment is None:
                    return False

                assessment.attempts += 1
                assessment.saved_context_json = context
                arm_retry(assessment, "llm")
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

    settings = get_effective_settings(session)

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
