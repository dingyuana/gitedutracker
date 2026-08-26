from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from app.models import Assessment, DailyPlan, GithubActivity, ScoringConfig, Student
from app.services.ai_scoring_service import LLMInvalidResponse, score_student
from app.services.github_snapshot import sync_day
from app.services.scoring_engine import compute_final
from app.services.email_service import send_daily_comments
from app.services.settings_service import get_effective_settings
from app.services.mirror_service import extract_day_activity, extract_snapshot


def run_today(
    target_date: date,
    session: Optional[Session] = None,
    only_missing: bool = False,
    eval_mode: str = "diff",
    project_id: Optional[int] = None,
    progress_cb=None,
) -> dict:
    """Run the full auto-scoring pipeline for a given date.

    1. Sync GitHub activity for all students.
    2. Find all applicable DailyPlans for the date.
    3. For each (student, project, date) combo: score → compute → persist.
       only_missing=True 时跳过已有 done 评测的组合（failed 仍会重试）。
       eval_mode="diff" 附带当日真实 diff；"full" 附带全项目代码快照。
    4. LLM failures are caught and stored as failed with retry info.

    Returns:
        {"success": int, "failed": int, "details": [...]}
    """
    if session is None:
        from app.database import get_session
        session = next(get_session())

    settings = get_effective_settings(session)

    all_students = session.exec(select(Student)).all()
    if project_id is not None:
        all_students = [s for s in all_students if s.project_id == project_id]
    student_map = {s.id: s for s in all_students}

    # Step 1: build (student, plan) pairs first — sync scope derives from pairs
    all_plans = session.exec(
        select(DailyPlan).where(DailyPlan.date == target_date)
    ).all()

    pairs: list[tuple[Student, DailyPlan]] = []
    for plan in all_plans:
        if plan.student_id is not None:
            s_ = student_map.get(plan.student_id)
            if s_ is not None:
                pairs.append((s_, plan))
            continue
        for s_ in all_students:
            if s_.project_id == plan.project_id:
                pairs.append((s_, plan))
    unassigned = [s.name for s in all_students if s.project_id is None]
    if unassigned and all_plans:
        import logging
        logging.getLogger(__name__).warning(
            "以下学生未归属任何项目，已跳过评测: %s", ", ".join(unassigned)
        )

    success_count = 0
    failed_count = 0
    details: list[dict] = []
    skipped_existing = 0

    done_keys = set()
    if only_missing:
        done_keys = {
            (a.student_id, a.project_id)
            for a in session.exec(
                select(Assessment).where(
                    Assessment.date == target_date, Assessment.status == "done"
                )
            ).all()
        }

    pairs = [(s_, p_) for s_, p_ in pairs
             if not (only_missing and (s_.id, p_.project_id) in done_keys)]
    total_to_score = len(pairs)

    # Step 2: sync GitHub activity ONLY for paired students
    target_students = list({s_.id: s_ for s_, _ in pairs}.values())
    sync_day(target_date, session, students=target_students)

    scored_count = 0

    if progress_cb and total_to_score > 0:
        try:
            progress_cb(0, total_to_score, "")
        except Exception:
            pass

    for student, plan in pairs:
        if only_missing and (student.id, plan.project_id) in done_keys:
            skipped_existing += 1
            continue
        activity = session.exec(
            select(GithubActivity).where(
                GithubActivity.student_id == student.id,
                GithubActivity.date == target_date,
            )
        ).first()

        if activity is None or activity.status != "ok":
            # No activity available, skip
            continue

        if eval_mode != "full" and activity.commits_count == 0 \
                and (activity.loc_additions + activity.loc_deletions) == 0:
            empty_comment = f"{target_date} 无代码提交，当日工作为空。"
            assessment = session.exec(
                select(Assessment).where(
                    Assessment.student_id == student.id,
                    Assessment.project_id == plan.project_id,
                    Assessment.date == target_date,
                )
            ).first()
            if assessment is None:
                assessment = Assessment(student_id=student.id, project_id=plan.project_id, date=target_date)
                session.add(assessment)
            assessment.status = "done"
            assessment.total_score = 0
            assessment.quality_score = 0
            assessment.match_score = 0
            assessment.schedule_status = "ontime"
            assessment.comment = empty_comment
            assessment.evaluated_at = datetime.now(timezone.utc)

            success_count += 1
            details.append({
                "student_id": student.id,
                "student_name": student.name,
                "project_id": plan.project_id,
                "status": "empty",
                "total_score": 0,
            })
            if progress_cb:
                try:
                    progress_cb(scored_count + success_count + failed_count,
                                total_to_score, student.name)
                except Exception:
                    pass
            continue

        context = {
            "plan_content": plan.content,
            "commits": json.loads(activity.commits_json) if activity.commits_json else [],
            "prs_opened": activity.prs_opened,
            "prs_merged": activity.prs_merged,
            "loc_additions": activity.loc_additions,
            "loc_deletions": activity.loc_deletions,
            "student_id": student.id,
        }

        try:
            if eval_mode == "full":
                snap = extract_snapshot(student.github_repo)
                context["project_files"] = snap.get("files", [])
            else:
                local = extract_day_activity(student.github_repo, target_date)
                context["code_diffs"] = local.get("code_diffs", [])
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "代码提取失败 student_id=%s: %s", student.id, e
            )
            context.setdefault("code_diffs", [])
            context.setdefault("project_files", [])

        # Upsert assessment by (student_id, project_id, date)
        assessment = session.exec(
            select(Assessment).where(
                Assessment.student_id == student.id,
                Assessment.project_id == plan.project_id,
                Assessment.date == target_date,
            )
        ).first()

        if assessment is None:
            assessment = Assessment(
                student_id=student.id,
                project_id=plan.project_id,
                date=target_date,
            )
            session.add(assessment)

        assessment.attempts += 1

        try:
            subscores = score_student(context, settings)

            config = session.exec(select(ScoringConfig)).first()
            if config is None:
                from app.models import ScoringConfig as _DefaultConfig
                config = _DefaultConfig()

            subscores["loc"] = context["loc_additions"] + context["loc_deletions"]
            engine_input = {
                "loc": subscores["loc"],
                "volume": subscores.get("volume"),
                "quality": subscores.get("quality_score", 0),
                "match": subscores.get("match_score", 0),
                "schedule_status": subscores.get("schedule_status", "ontime"),
            }
            total_score = compute_final(engine_input, config)

            assessment.status = "done"
            assessment.quality_score = subscores.get("quality_score")
            assessment.match_score = subscores.get("match_score")
            assessment.schedule_status = subscores.get("schedule_status", "ontime")
            assessment.total_score = total_score
            assessment.comment = subscores.get("comment", "")
            assessment.evaluated_at = datetime.now(timezone.utc)

            success_count += 1
            details.append({
                "student_id": student.id,
                "student_name": student.name,
                "project_id": plan.project_id,
                "status": "done",
                "total_score": total_score,
            })

        except LLMInvalidResponse as e:
            assessment.status = "failed"
            assessment.saved_context_json = json.dumps(context, ensure_ascii=False)
            assessment.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=2)
            assessment.schedule_status = "ontime"

            failed_count += 1
            details.append({
                "student_id": student.id,
                "student_name": student.name,
                "project_id": plan.project_id,
                "status": "failed",
                "error": str(e),
            })

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "评分异常 student=%s: %s", student.name, e
            )
            assessment.status = "failed"
            assessment.saved_context_json = json.dumps(context, ensure_ascii=False)
            assessment.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=2)
            assessment.schedule_status = "ontime"

            failed_count += 1
            details.append({
                "student_id": student.id,
                "student_name": student.name,
                "project_id": plan.project_id,
                "status": "failed",
                "error": str(e)[:200],
            })

        if progress_cb:
            try:
                progress_cb(scored_count + success_count + failed_count,
                            total_to_score, student.name)
            except Exception:
                pass

    session.commit()

    try:
        send_daily_comments(target_date, session)
    except Exception as e:
        import logging
        logging.warning("邮件发送失败: %s", e)

    return {
        "success": success_count,
        "failed": failed_count,
        "skipped_existing": skipped_existing,
        "details": details,
    }
