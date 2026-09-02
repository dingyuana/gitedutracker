from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from app.models import Assessment, DailyPlan, GithubActivity, ScoringConfig, Student
from app.services.ai_scoring_service import LLMInvalidResponse, score_student
from app.services.github_snapshot import sync_day
from app.services.scoring_engine import compute_final
from app.services.email_service import send_daily_comments
from app.services.settings_service import get_effective_settings
from app.services.mirror_service import extract_day_activity, extract_snapshot, repo_total_loc

# SQLite 单写者：串行化所有评测写库，避免并发评测触发 database is locked
_run_lock = threading.Lock()


def _student_repo(student) -> str:
    """优先返回完整仓库 URL（含 github/gitee 平台信息），缺失时退回 owner/repo。"""
    return student.github_url or student.github_repo


@dataclass
class _AggregatePlan:
    """全项目综合评测（eval_mode='full'）的聚合计划：一个学生一个。"""
    project_id: int
    content: str


def run_today(
    target_date: date,
    session: Optional[Session] = None,
    only_missing: bool = False,
    eval_mode: str = "diff",
    project_id: Optional[int] = None,
    plan_id: Optional[int] = None,
    sample_size: int = None,
    progress_cb=None,
    send_email: bool = False,
) -> dict:
    """Run the full auto-scoring pipeline for a given date.

    1. Sync GitHub activity for all students.
    2. Find all applicable DailyPlans for the date.
    3. For each (student, project, date) combo: score → compute → persist.
       only_missing=True 时跳过已有 done 评测的组合（failed 仍会重试，
       即上次检测失败的学生仍会被重新检测）。
       eval_mode="diff" 附带当日真实 diff；"full" 附带全项目代码快照。
       plan_id 指定后仅使用该计划的当日评测目标。
       send_email=True 时评测完成后发送评估邮件（默认 False 不发送）。
    4. LLM failures are caught and stored as failed with retry info.

    Returns:
        {"success": int, "failed": int, "details": [...]}
    """
    with _run_lock:
        return _run_today(
            target_date, session, only_missing, eval_mode,
            project_id, plan_id, sample_size, progress_cb, send_email,
        )


def _run_today(
    target_date: date,
    session: Optional[Session],
    only_missing: bool,
    eval_mode: str,
    project_id: Optional[int],
    plan_id: Optional[int],
    sample_size: int,
    progress_cb,
    send_email: bool = False,
) -> dict:
    if session is None:
        from app.database import get_session
        session = next(get_session())

    if eval_mode == "full":
        return _run_today_full(
            target_date, session, only_missing, project_id, progress_cb, send_email,
        )
    return _run_today_diff(
        target_date, session, only_missing, project_id, plan_id, sample_size, progress_cb, send_email,
    )


def _run_today_full(
    target_date: date,
    session: Session,
    only_missing: bool,
    project_id: Optional[int],
    progress_cb,
    send_email: bool = False,
) -> dict:
    """全项目综合评测：对项目全部历史计划做聚合，评测学生当前完整代码。

    与 diff 模式的差异：
    - 不做 GitHub 当日同步（sync_day）、不设置活动门槛、不触发空日短路；
    - 忽略 plan_id，每个学生只产出一条 eval_type='full' 的 Assessment；
    - 计划聚合范围：项目内 date <= target_date 的全体计划 + 该生专属计划；
    - 上下文以全量代码快照 + 累计代码行数为依据，无单日 commits。
    """
    settings = get_effective_settings(session)

    all_students = session.exec(select(Student)).all()
    full_pairs = _build_full_pairs(all_students, target_date, project_id, session)

    success_count = 0
    failed_count = 0
    skipped_existing = 0
    details: list[dict] = []

    done_keys = set()
    if only_missing and full_pairs:
        done_keys = {
            (a.student_id, a.project_id, a.date)
            for a in session.exec(
                select(Assessment).where(
                    Assessment.status == "done",
                    Assessment.date == target_date,
                    Assessment.eval_type == "full",
                )
            ).all()
        }

    total_to_score = len(full_pairs)

    if progress_cb and total_to_score > 0:
        try:
            progress_cb(0, total_to_score, "")
        except Exception:
            pass

    scored_count = 0
    for student in all_students:
        agg = full_pairs.get(student.id)
        if agg is None:
            continue
        if only_missing and (student.id, agg.project_id, target_date) in done_keys:
            skipped_existing += 1
            continue

        context = _build_full_context(student, agg)

        # Upsert assessment by (student_id, project_id, date, eval_type)
        assessment = session.exec(
            select(Assessment).where(
                Assessment.student_id == student.id,
                Assessment.project_id == agg.project_id,
                Assessment.date == target_date,
                Assessment.eval_type == "full",
            )
        ).first()

        if assessment is None:
            assessment = Assessment(
                student_id=student.id,
                project_id=agg.project_id,
                date=target_date,
                eval_type="full",
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
                "bonus": subscores.get("bonus", 0),
            }
            total_score = compute_final(engine_input, config)

            assessment.status = "done"
            assessment.quality_score = subscores.get("quality_score")
            assessment.match_score = subscores.get("match_score")
            assessment.schedule_status = subscores.get("schedule_status", "ontime")
            assessment.total_score = total_score
            assessment.bonus_score = subscores.get("bonus")
            assessment.comment = subscores.get("comment", "")
            assessment.evaluated_at = datetime.now(timezone.utc)

            success_count += 1
            details.append({
                "student_id": student.id,
                "student_name": student.name,
                "project_id": agg.project_id,
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
                "project_id": agg.project_id,
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
                "project_id": agg.project_id,
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

    if send_email:
        try:
            send_daily_comments(target_date, session)
        except Exception as e:
            import logging
            logging.warning("邮件发送失败 (%s): %s", target_date, e)

    return {
        "success": success_count,
        "failed": failed_count,
        "skipped_existing": skipped_existing,
        "details": details,
    }


def _build_full_pairs(
    all_students: list,
    target_date: date,
    project_id: Optional[int],
    session: Session,
) -> dict[int, _AggregatePlan]:
    scope = [s for s in all_students if project_id is None or s.project_id == project_id]
    result: dict[int, _AggregatePlan] = {}
    for s in scope:
        plans = session.exec(
            select(DailyPlan).where(
                DailyPlan.project_id == s.project_id,
                DailyPlan.date <= target_date,
                (DailyPlan.student_id.is_(None)) | (DailyPlan.student_id == s.id),
            )
        ).all()
        if not plans:
            continue
        content = "\n".join(p.content for p in sorted(plans, key=lambda p: p.date) if p.content)
        result[s.id] = _AggregatePlan(project_id=s.project_id, content=content)
    return result


def _build_full_context(student, agg: _AggregatePlan) -> dict:
    context = {
        "eval_mode": "full",
        "plan_content": agg.content,
        "commits": [],
        "prs_opened": 0,
        "prs_merged": 0,
        "loc_additions": 0,
        "loc_deletions": 0,
        "student_id": student.id,
        "project_id": agg.project_id,
    }
    repo = _student_repo(student)
    try:
        snap = extract_snapshot(repo)
        context["project_files"] = snap.get("files", [])
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "快照提取失败 student_id=%s: %s", student.id, e
        )
        context["project_files"] = []
    try:
        context["loc_additions"] = repo_total_loc(repo)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "累计代码行统计失败 student_id=%s: %s", student.id, e
        )
    return context


def _run_today_diff(
    target_date: date,
    session: Session,
    only_missing: bool,
    project_id: Optional[int],
    plan_id: Optional[int],
    sample_size: int,
    progress_cb,
    send_email: bool = False,
) -> dict:
    settings = get_effective_settings(session)

    all_students = session.exec(select(Student)).all()
    if project_id is not None:
        all_students = [s for s in all_students if s.project_id == project_id]
    student_map = {s.id: s for s in all_students}

    # Step 1: build (student, plan) pairs first — sync scope derives from pairs
    plan_q = select(DailyPlan)
    if plan_id is not None:
        plan_q = plan_q.where(DailyPlan.id == plan_id)
    elif project_id is not None:
        plan_q = plan_q.where(DailyPlan.project_id == project_id)
    else:
        plan_q = plan_q.where(DailyPlan.date == target_date)
    all_plans = session.exec(plan_q).all()

    pairs: list[tuple[Student, DailyPlan]] = []
    for plan in all_plans:
        if plan.student_id is not None:
            s_ = student_map.get(plan.student_id)
            if s_ is not None:
                pairs.append((s_, plan))
            continue
        if sample_size is not None and sample_size > 0:
            import random as _random
            candidates = [s_ for s_ in all_students if s_.project_id == plan.project_id]
            _random.shuffle(candidates)
            sampled = candidates[:sample_size]
            for s_ in sampled:
                pairs.append((s_, plan))
        else:
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
    involved_dates = sorted({p_.date for _, p_ in pairs})
    if only_missing and involved_dates:
        done_keys = {
            (a.student_id, a.project_id, a.date)
            for a in session.exec(
                select(Assessment).where(
                    Assessment.status == "done",
                    Assessment.date.in_(involved_dates),
                    Assessment.eval_type == "diff",
                )
            ).all()
        }

    pairs = [(s_, p_) for s_, p_ in pairs
             if not (only_missing and (s_.id, p_.project_id, p_.date) in done_keys)]
    total_to_score = len(pairs)

    # Step 2: sync GitHub activity ONLY for paired students (per involved date)
    target_students = list({s_.id: s_ for s_, _ in pairs}.values())
    for d in sorted({p_.date for _, p_ in pairs}):
        sync_day(d, session, students=target_students)

    scored_count = 0

    if progress_cb and total_to_score > 0:
        try:
            progress_cb(0, total_to_score, "")
        except Exception:
            pass

    for student, plan in pairs:
        if only_missing and (student.id, plan.project_id, plan.date) in done_keys:
            skipped_existing += 1
            continue
        activity = session.exec(
            select(GithubActivity).where(
                GithubActivity.student_id == student.id,
                GithubActivity.date == plan.date,
            )
        ).first()

        if activity is None or activity.status != "ok":
            reason = "GitHub 同步失败，无法获取代码活动数据"
            if activity and activity.status == "failed":
                reason = "GitHub 同步失败（仓库不存在、无权限或网络异常）"
            assessment = session.exec(
                select(Assessment).where(
                    Assessment.student_id == student.id,
                    Assessment.project_id == plan.project_id,
                    Assessment.date == plan.date,
                    Assessment.eval_type == "diff",
                )
            ).first()
            if assessment is None:
                assessment = Assessment(student_id=student.id, project_id=plan.project_id, date=plan.date)
                session.add(assessment)
            assessment.status = "failed"
            assessment.total_score = 0
            assessment.quality_score = 0
            assessment.match_score = 0
            assessment.schedule_status = "ontime"
            assessment.comment = f"{plan.date} {reason}。"
            assessment.evaluated_at = datetime.now(timezone.utc)
            session.commit()
            failed_count += 1
            continue

        if activity.commits_count == 0 \
                and (activity.loc_additions + activity.loc_deletions) == 0:
            empty_comment = (f"{plan.date} 今天没有看到你的代码提交。没关系的，有时候是在思考、"
                             f"调试或者遇到了困难。如果有什么问题或卡住了，随时可以告诉我，"
                             f"我们一起分析解决，别灰心，加油！")
            assessment = session.exec(
                select(Assessment).where(
                    Assessment.student_id == student.id,
                    Assessment.project_id == plan.project_id,
                    Assessment.date == plan.date,
                    Assessment.eval_type == "diff",
                )
            ).first()
            if assessment is None:
                assessment = Assessment(student_id=student.id, project_id=plan.project_id, date=plan.date)
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
            local = extract_day_activity(_student_repo(student), plan.date)
            context["code_diffs"] = local.get("code_diffs", [])
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "代码提取失败 student_id=%s: %s", student.id, e
            )
            context.setdefault("code_diffs", [])

        # Upsert assessment by (student_id, project_id, date, eval_type='diff')
        assessment = session.exec(
            select(Assessment).where(
                Assessment.student_id == student.id,
                Assessment.project_id == plan.project_id,
                Assessment.date == plan.date,
                Assessment.eval_type == "diff",
            )
        ).first()

        if assessment is None:
            assessment = Assessment(
                student_id=student.id,
                project_id=plan.project_id,
                date=plan.date,
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

    if send_email:
        for d in sorted({p_.date for _, p_ in pairs}):
            try:
                send_daily_comments(d, session)
            except Exception as e:
                import logging
                logging.warning("邮件发送失败 (%s): %s", d, e)

    return {
        "success": success_count,
        "failed": failed_count,
        "skipped_existing": skipped_existing,
        "details": details,
    }
