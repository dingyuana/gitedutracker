import datetime
import tempfile
from datetime import date as _date
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from sqlmodel import Session, select, delete

from app.database import get_session
from app.models import Student, Project, DailyPlan, GithubActivity, Assessment, ScoringConfig
from app.utils.export import export_daily
from app.services.import_service import import_students
from app.services.pipeline import run_today
from app.services.eval_jobs import start_eval_job, get_job, is_running
from app.middleware.auth import require_auth, login_endpoint, security

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request, auth_check=Depends(require_auth), session: Session = Depends(get_session)):
    today = _date.today()
    projects = session.exec(select(Project)).all()

    active_cards = []
    done_cards = []
    for p in projects:
        progress_pct = None
        if p.start_date and today < p.start_date:
            day_label = "未开始"
        elif p.end_date and today > p.end_date:
            day_label = "已结束"
        elif p.start_date:
            day_n = (today - p.start_date).days + 1
            day_label = f"第{day_n}天"
            if p.end_date:
                total_days = (p.end_date - p.start_date).days + 1
                day_label += f" / 共{total_days}天"
                progress_pct = round(day_n / total_days * 100)
        else:
            day_label = "未排期"

        plans_today = session.exec(
            select(DailyPlan).where(DailyPlan.project_id == p.id, DailyPlan.date == today)
        ).all()
        assessed_today = session.exec(
            select(Assessment).where(Assessment.project_id == p.id, Assessment.date == today)
        ).all()
        done_today = [a for a in assessed_today if a.status == "done"]

        card = {
            "project": p,
            "day_label": day_label,
            "progress_pct": progress_pct,
            "plan_count": len(plans_today),
            "plan_summary": plans_today[0].content if plans_today else None,
            "assessed_count": len(done_today),
        }
        if getattr(p, "status", "active") == "done":
            done_cards.append(card)
        else:
            active_cards.append(card)

    templates = request.app.state.templates
    return templates.TemplateResponse(request, "index.html", {
        "active_cards": active_cards,
        "done_cards": done_cards,
        "today": today,
    })


@router.get("/students", response_class=HTMLResponse)
def students_page(request: Request, auth_check=Depends(require_auth), session: Session = Depends(get_session)):
    student_list = session.exec(select(Student)).all()
    projects = session.exec(select(Project)).all()
    project_map = {p.id: p.name for p in projects}
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "students.html", {
        "students": student_list,
        "projects": projects,
        "project_map": project_map,
    })


@router.post("/students", response_class=HTMLResponse)
@router.post("/students/import", response_class=HTMLResponse)
def import_students_page(
    request: Request,
    auth_check=Depends(require_auth),
    file: UploadFile = File(...),
    project_id: int = Form(None),
    session: Session = Depends(get_session),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少导入文件")
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name
    try:
        import_students(tmp_path, session=session, project_id=project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        import os
        os.unlink(tmp_path)
    if project_id:
        return RedirectResponse(url=f"/projects/{project_id}/students", status_code=303)
    return RedirectResponse(url="/students", status_code=303)


@router.post("/students/add", response_class=HTMLResponse)
def add_student(
    request: Request,
    auth_check=Depends(require_auth),
    name: str = Form(...),
    email: str = Form(""),
    github_repo: str = Form(...),
    project_id: int = Form(None),
    session: Session = Depends(get_session),
):
    student = Student(name=name.strip(), email=email.strip(), github_repo=github_repo.strip())
    if project_id:
        student.project_id = project_id
    session.add(student)
    session.commit()
    return RedirectResponse(url=f"/projects/{project_id}" if project_id else "/", status_code=303)


@router.post("/students/{student_id}/update", response_class=HTMLResponse)
def update_student(
    request: Request,
    student_id: int,
    auth_check=Depends(require_auth),
    name: str = Form(...),
    email: str = Form(""),
    github_repo: str = Form(...),
    session: Session = Depends(get_session),
):
    student = session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="学生不存在")

    repo_raw = github_repo.strip()
    dup = session.exec(
        select(Student).where(Student.email == email.strip(), Student.id != student_id)
    ).first()
    if dup is not None:
        raise HTTPException(status_code=400, detail="邮箱已被其他学生使用")

    # 复用模型校验器：完整 URL → github_repo 规范化 + github_url 保存；owner/repo → github_url 清空
    parsed = Student.model_validate({
        "name": name.strip(),
        "email": email.strip(),
        "github_repo": repo_raw,
    })
    student.name = parsed.name
    student.email = parsed.email
    student.github_repo = parsed.github_repo
    student.github_url = parsed.github_url
    session.add(student)
    session.commit()
    return RedirectResponse(
        url=f"/projects/{student.project_id}/students" if student.project_id else "/students",
        status_code=303,
    )


@router.post("/students/{student_id}/delete", response_class=HTMLResponse)
def delete_student(
    request: Request,
    student_id: int,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    student = session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="学生不存在")
    project_id = student.project_id
    session.delete(student)
    session.commit()
    return RedirectResponse(url=f"/projects/{project_id}" if project_id else "/", status_code=303)


def _cascade_delete_students(session: Session, students):
    ids = [s.id for s in students]
    if not ids:
        return
    # 重新查询以确保使用的是 session 中的当前对象（避免 ObjectDeletedError）
    students_to_delete = list(session.exec(select(Student).where(Student.id.in_(ids))))
    session.exec(delete(Assessment).where(Assessment.student_id.in_(ids)))
    session.exec(delete(GithubActivity).where(GithubActivity.student_id.in_(ids)))
    plans = session.exec(select(DailyPlan).where(DailyPlan.student_id.in_(ids))).all()
    for p in plans:
        p.student_id = None
    for s in students_to_delete:
        session.delete(s)
    session.commit()


@router.post("/projects/{project_id}/students/clear", response_class=HTMLResponse)
def clear_project_students(
    request: Request,
    project_id: int,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    students = session.exec(
        select(Student).where(Student.project_id == project_id)
    ).all()
    _cascade_delete_students(session, students)
    return RedirectResponse(url=f"/projects/{project_id}/students", status_code=303)


@router.post("/students/clear", response_class=HTMLResponse)
def clear_all_students(
    request: Request,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    students = session.exec(select(Student)).all()
    _cascade_delete_students(session, students)
    return RedirectResponse(url="/students", status_code=303)


@router.post("/config", response_class=HTMLResponse)
def save_config_page(
    request: Request,
    auth_check=Depends(require_auth),
    w_volume: float = Form(0.333),
    w_quality: float = Form(0.333),
    w_match: float = Form(0.333),
    loc_threshold: int = Form(100),
    schedule_bonus: float = Form(5.0),
    schedule_penalty: float = Form(-5.0),
    session: Session = Depends(get_session),
):
    config = session.exec(select(ScoringConfig)).first()
    if config is None:
        from app.services.config_seed import seed_config
        seed_config(session)
        config = session.exec(select(ScoringConfig)).first()
    config.w_volume = w_volume
    config.w_quality = w_quality
    config.w_match = w_match
    config.loc_threshold = loc_threshold
    config.schedule_bonus = schedule_bonus
    config.schedule_penalty = schedule_penalty
    session.add(config)
    session.commit()
    return RedirectResponse(url="/config", status_code=303)


@router.get("/projects", response_class=HTMLResponse)
def projects_page():
    return RedirectResponse(url="/", status_code=303)


@router.post("/projects", response_class=HTMLResponse)
def create_project_page(
    request: Request,
    auth_check=Depends(require_auth),
    name: str = Form(...),
    description: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    session: Session = Depends(get_session),
):
    project = Project(name=name.strip())
    if description.strip():
        project.description = description.strip()
    if start_date.strip():
        project.start_date = datetime.date.fromisoformat(start_date.strip())
    if end_date.strip():
        project.end_date = datetime.date.fromisoformat(end_date.strip())
    project.status = "active"
    session.add(project)
    session.commit()
    return RedirectResponse(url="/", status_code=303)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail_page(
    request: Request,
    project_id: int,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    from datetime import date as _today
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    today = _today.today()
    students = session.exec(select(Student).where(Student.project_id == project_id)).all()
    plans = session.exec(
        select(DailyPlan).where(DailyPlan.project_id == project_id)
    ).all()
    plans_sorted = sorted(plans, key=lambda p: p.date, reverse=True)

    assessments = session.exec(
        select(Assessment).where(Assessment.project_id == project_id)
    ).all()
    by_date: dict = {}
    for a in assessments:
        if a.status not in ("done", "failed"):
            continue
        student = session.get(Student, a.student_id)
        by_date.setdefault(a.date, []).append({
            "student_name": student.name if student else f"#{a.student_id}",
            "total_score": a.total_score,
            "comment": a.comment,
            "status": a.status,
        })
    date_plan_map = {p.date: p.content for p in plans}
    assessments_by_date = [
        (d, items, date_plan_map.get(d, ""))
        for d, items in sorted(by_date.items(), key=lambda kv: kv[0], reverse=True)
    ]

    from app.utils.svg_chart import build_line_chart

    done_sorted = sorted(
        (a for a in assessments if a.status == "done" and a.total_score is not None),
        key=lambda a: a.date,
    )
    score_by_date: dict = {}
    per_student: dict = {}
    for a in done_sorted:
        score_by_date.setdefault(a.date, []).append(a.total_score)
        per_student.setdefault(a.student_id, []).append(a)
    avg_series = [
        (d.strftime("%m-%d"), round(sum(vs) / len(vs), 1))
        for d, vs in sorted(score_by_date.items())
    ]
    avg_chart = build_line_chart(avg_series, title="项目每日平均分", color="#1a73e8")

    student_charts = []
    for sid, alist in sorted(per_student.items(), key=lambda kv: kv[1][0].date):
        st = session.get(Student, sid)
        sname = st.name if st else f"#{sid}"
        series = [(a.date.strftime("%m-%d"), a.total_score) for a in alist]
        student_charts.append({
            "name": sname,
            "count": len(series),
            "chart": build_line_chart(series, title=f"{sname} · 分数变化", color="#34a853"),
        })

    day_label = None
    progress_pct = None
    if project.start_date:
        if today < project.start_date:
            day_label = "未开始"
        elif project.end_date and today > project.end_date:
            day_label = "已结束"
        else:
            day_n = (today - project.start_date).days + 1
            day_label = f"第{day_n}天"
            if project.end_date:
                total_days = (project.end_date - project.start_date).days + 1
                day_label += f" / 共{total_days}天"
                progress_pct = round(day_n / total_days * 100)

    templates = request.app.state.templates
    return templates.TemplateResponse(request, "project_detail.html", {
        "project": project,
        "students": students,
        "plans": plans_sorted,
        "assessments_by_date": assessments_by_date,
        "day_label": day_label,
        "progress_pct": progress_pct,
        "avg_chart": avg_chart,
        "student_charts": student_charts,
    })


def _load_project_ctx(session, project_id):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    students = session.exec(select(Student).where(Student.project_id == project_id)).all()
    return project, students


def _load_charts(session, project_id):
    from app.utils.svg_chart import build_line_chart
    assessments = session.exec(
        select(Assessment).where(Assessment.project_id == project_id)
    ).all()
    done_sorted = sorted(
        (a for a in assessments if a.status == "done" and a.total_score is not None),
        key=lambda a: a.date,
    )
    score_by_date: dict = {}
    per_student: dict = {}
    for a in done_sorted:
        score_by_date.setdefault(a.date, []).append(a.total_score)
        per_student.setdefault(a.student_id, []).append(a)
    avg_series = [
        (d.strftime("%m-%d"), round(sum(vs) / len(vs), 1))
        for d, vs in sorted(score_by_date.items())
    ]
    avg_chart = build_line_chart(avg_series, title="项目每日平均分", color="#1a73e8")
    student_charts = []
    for sid, alist in sorted(per_student.items(), key=lambda kv: kv[1][0].date):
        st = session.get(Student, sid)
        sname = st.name if st else f"#{sid}"
        series = [(a.date.strftime("%m-%d"), a.total_score) for a in alist]
        student_charts.append({
            "name": sname, "count": len(series),
            "chart": build_line_chart(series, title=f"{sname} · 分数变化", color="#34a853"),
        })
    return avg_chart, student_charts


def _load_assessments(session, project_id):
    plans = session.exec(select(DailyPlan).where(DailyPlan.project_id == project_id)).all()
    date_plan_map = {p.date: p.content for p in plans}
    assessments = session.exec(
        select(Assessment).where(Assessment.project_id == project_id)
    ).all()
    by_date: dict = {}
    for a in assessments:
        if a.status not in ("done", "failed"):
            continue
        student = session.get(Student, a.student_id)
        by_date.setdefault(a.date, []).append({
            "id": a.id,
            "student_name": student.name if student else f"#{a.student_id}",
            "total_score": a.total_score,
            "comment": a.comment,
            "status": a.status,
        })
    return [
        (d, items, date_plan_map.get(d, ""))
        for d, items in sorted(by_date.items(), key=lambda kv: kv[0], reverse=True)
    ]


@router.get("/projects/{project_id}/students", response_class=HTMLResponse)
def project_students_page(
    request: Request, project_id: int,
    auth_check=Depends(require_auth), session: Session = Depends(get_session),
):
    project, students = _load_project_ctx(session, project_id)
    return request.app.state.templates.TemplateResponse(request, "project_students.html", {
        "project": project, "students": students,
    })


@router.get("/projects/{project_id}/plans", response_class=HTMLResponse)
def project_plans_page(
    request: Request, project_id: int,
    auth_check=Depends(require_auth), session: Session = Depends(get_session),
):
    from datetime import date as _today
    project, students = _load_project_ctx(session, project_id)
    plans = sorted(
        session.exec(select(DailyPlan).where(DailyPlan.project_id == project_id)).all(),
        key=lambda p: p.date, reverse=True,
    )
    if "application/json" in request.headers.get("accept", ""):
        filtered = plans
        date_str = request.query_params.get("date")
        if date_str:
            try:
                filter_date = _date.fromisoformat(date_str)
                filtered = [p for p in plans if p.date == filter_date]
            except ValueError:
                pass
        return JSONResponse([
            {"id": p.id, "date": str(p.date), "content": p.content}
            for p in filtered
        ])
    return request.app.state.templates.TemplateResponse(request, "project_plans.html", {
        "project": project, "students": students, "plans": plans,
        "today": _today.today(),
    })


@router.get("/projects/{project_id}/charts", response_class=HTMLResponse)
def project_charts_page(
    request: Request, project_id: int,
    auth_check=Depends(require_auth), session: Session = Depends(get_session),
):
    project, _ = _load_project_ctx(session, project_id)
    avg_chart, student_charts = _load_charts(session, project_id)
    return request.app.state.templates.TemplateResponse(request, "project_charts.html", {
        "project": project, "avg_chart": avg_chart, "student_charts": student_charts,
    })


@router.get("/projects/{project_id}/assessments", response_class=HTMLResponse)
def project_assessments_page(
    request: Request, project_id: int,
    auth_check=Depends(require_auth), session: Session = Depends(get_session),
):
    project, _ = _load_project_ctx(session, project_id)
    assessments_by_date = _load_assessments(session, project_id)
    return request.app.state.templates.TemplateResponse(request, "project_assessments.html", {
        "project": project, "assessments_by_date": assessments_by_date,
    })


@router.post("/projects/{project_id}/complete", response_class=HTMLResponse)
def complete_project(
    request: Request,
    project_id: int,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    project.status = "done"
    session.add(project)
    session.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/projects/{project_id}/reopen", response_class=HTMLResponse)
def reopen_project(
    request: Request,
    project_id: int,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    project.status = "active"
    session.add(project)
    session.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/projects", response_class=HTMLResponse)
def create_project_page(
    request: Request,
    auth_check=Depends(require_auth),
    name: str = Form(...),
    description: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    session: Session = Depends(get_session),
):
    project = Project(name=name.strip())
    if description.strip():
        project.description = description.strip()
    if start_date.strip():
        project.start_date = datetime.date.fromisoformat(start_date.strip())
    if end_date.strip():
        project.end_date = datetime.date.fromisoformat(end_date.strip())
    session.add(project)
    session.commit()
    return RedirectResponse(url="/", status_code=303)


@router.get("/projects/{project_id}/edit", response_class=HTMLResponse)
def edit_project_page(
    request: Request,
    project_id: int,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "project_edit.html", {"project": project})


@router.post("/projects/{project_id}/edit", response_class=HTMLResponse)
def update_project_page(
    request: Request,
    project_id: int,
    auth_check=Depends(require_auth),
    name: str = Form(...),
    description: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    project.name = name.strip()
    project.description = description.strip() if description.strip() else None
    project.start_date = datetime.date.fromisoformat(start_date.strip()) if start_date.strip() else None
    project.end_date = datetime.date.fromisoformat(end_date.strip()) if end_date.strip() else None
    session.add(project)
    session.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/projects/{project_id}/delete", response_class=HTMLResponse)
def delete_project_page(
    request: Request,
    project_id: int,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    from app.models import GithubActivity
    for plan in session.exec(select(DailyPlan).where(DailyPlan.project_id == project_id)).all():
        session.delete(plan)
    for assessment in session.exec(select(Assessment).where(Assessment.project_id == project_id)).all():
        session.delete(assessment)
    session.delete(project)
    session.commit()
    return RedirectResponse(url="/", status_code=303)


@router.post("/plans", response_class=HTMLResponse)
def create_plan_page(
    request: Request,
    auth_check=Depends(require_auth),
    date: str = Form(...),
    project_id: int = Form(...),
    content: str = Form(...),
    student_id: str = Form(""),
    session: Session = Depends(get_session),
):
    plan = DailyPlan(
        date=datetime.date.fromisoformat(date),
        project_id=project_id,
        content=content.strip(),
        student_id=int(student_id) if student_id.strip() else None,
    )
    session.add(plan)
    session.commit()
    return RedirectResponse(url="/plans", status_code=303)


@router.get("/plans/{plan_id}/edit", response_class=HTMLResponse)
def edit_plan_page(
    request: Request,
    plan_id: int,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    plan = session.get(DailyPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    projects = session.exec(select(Project)).all()
    students = session.exec(select(Student)).all()
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "plan_edit.html", {
        "plan": plan,
        "projects": projects,
        "students": students,
    })


@router.post("/plans/{plan_id}/edit", response_class=HTMLResponse)
def update_plan_page(
    request: Request,
    plan_id: int,
    auth_check=Depends(require_auth),
    date: str = Form(...),
    project_id: int = Form(...),
    content: str = Form(...),
    student_id: str = Form(""),
    session: Session = Depends(get_session),
):
    plan = session.get(DailyPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    plan.date = datetime.date.fromisoformat(date)
    plan.project_id = project_id
    plan.content = content.strip()
    plan.student_id = int(student_id) if student_id.strip() else None
    session.add(plan)
    session.commit()
    return RedirectResponse(url="/plans", status_code=303)


@router.post("/plans/{plan_id}/delete", response_class=HTMLResponse)
def delete_plan_page(
    request: Request,
    plan_id: int,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    plan = session.get(DailyPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    session.delete(plan)
    session.commit()
    return RedirectResponse(url="/plans", status_code=303)


@router.get("/plans", response_class=HTMLResponse)
def plans_page(request: Request, auth_check=Depends(require_auth), session: Session = Depends(get_session)):
    plans = session.exec(
        select(DailyPlan).order_by(DailyPlan.date.desc())
    ).all()
    projects = session.exec(select(Project)).all()
    students = session.exec(select(Student)).all()
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "plans.html", {
        "plans": plans,
        "projects": projects,
        "students": students,
    })


@router.get("/config", response_class=HTMLResponse)
def config_page(request: Request, auth_check=Depends(require_auth), session: Session = Depends(get_session)):
    config = session.exec(select(ScoringConfig)).first()
    if config is None:
        from app.services.config_seed import seed_config
        config = seed_config(session)
    from app.services.settings_service import get_llm_config, get_smtp_config
    from app.config import get_settings
    llm_row = get_llm_config(session)
    env = get_settings()
    llm_current = {
        "llm_model": (llm_row.llm_model if llm_row and llm_row.llm_model else env.llm_model),
        "llm_base_url": (llm_row.llm_base_url if llm_row and llm_row.llm_base_url else env.llm_base_url),
        "llm_context_max_chars": (llm_row.llm_context_max_chars if llm_row and llm_row.llm_context_max_chars else env.llm_context_max_chars),
        "has_api_key": bool((llm_row.llm_api_key if llm_row else "") or env.llm_api_key),
    }
    smtp_row = get_smtp_config(session)
    smtp_current = {
        "smtp_host": (smtp_row.smtp_host if smtp_row and smtp_row.smtp_host else env.smtp_host),
        "smtp_port": (smtp_row.smtp_port if smtp_row and smtp_row.smtp_port else env.smtp_port),
        "smtp_user": (smtp_row.smtp_user if smtp_row and smtp_row.smtp_user else env.smtp_user),
        "smtp_from": (smtp_row.smtp_from if smtp_row and smtp_row.smtp_from else env.smtp_from),
        "has_password": bool((smtp_row.smtp_pass if smtp_row else "") or env.smtp_pass),
    }
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "config.html", {
        "config": config,
        "llm": llm_current,
        "smtp": smtp_current,
    })


@router.post("/config/llm", response_class=HTMLResponse)
def save_llm_config_page(
    request: Request,
    auth_check=Depends(require_auth),
    llm_model: str = Form(""),
    llm_base_url: str = Form(""),
    llm_api_key: str = Form(""),
    llm_context_max_chars: str = Form(""),
    session: Session = Depends(get_session),
):
    from app.services.settings_service import save_llm_config
    save_llm_config(
        session,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_context_max_chars=int(llm_context_max_chars) if llm_context_max_chars.strip().isdigit() else None,
    )
    return RedirectResponse(url="/config", status_code=303)


@router.post("/config/smtp", response_class=HTMLResponse)
def save_smtp_config_page(
    request: Request,
    auth_check=Depends(require_auth),
    smtp_host: str = Form(""),
    smtp_port: str = Form(""),
    smtp_user: str = Form(""),
    smtp_pass: str = Form(""),
    smtp_from: str = Form(""),
    session: Session = Depends(get_session),
):
    from app.services.settings_service import save_smtp_config
    save_smtp_config(
        session,
        smtp_host=smtp_host,
        smtp_port=int(smtp_port) if smtp_port.strip().isdigit() else None,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        smtp_from=smtp_from,
    )
    return RedirectResponse(url="/config", status_code=303)


@router.get("/results", response_class=HTMLResponse)
def results_page(
    request: Request,
    auth_check=Depends(require_auth),
    date: str = None,
    session: Session = Depends(get_session),
):
    target_date = datetime.date.fromisoformat(date) if date else None
    assessments = []
    if target_date:
        stmt = (
            select(Assessment, Student, Project)
            .join(Student, Assessment.student_id == Student.id)
            .join(Project, Assessment.project_id == Project.id)
            .where(Assessment.date == target_date)
            .order_by(Student.name, Project.name)
        )
        rows = session.exec(stmt).all()
        assessments = [{"assessment": a, "student": s, "project": p} for a, s, p in rows]
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "results.html", {
        "assessments": assessments,
        "date": target_date,
    })


@router.get("/export")
def export_page(
    auth_check=Depends(require_auth),
    date: str = None,
    fmt: str = "xlsx",
    session: Session = Depends(get_session),
):
    if fmt != "xlsx":
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="仅支持 xlsx 格式")
    if not date:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="缺少 date 参数")
    target_date = datetime.date.fromisoformat(date)
    xlsx_bytes = export_daily(target_date, session)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=results_{date}.xlsx"},
    )


@router.post("/run-today")
async def run_today_endpoint(
    request: Request,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    if is_running():
        return JSONResponse({"busy": True, "error": "已有评测任务正在进行，请稍后再试"},
                            status_code=409)
    qp = request.query_params
    form_data: dict = {}
    if "form" in request.headers.get("content-type", ""):
        form = await request.form()
        form_data = {k: form.get(k) for k in ("date", "only_missing", "redirect", "eval_mode")}

    date = qp.get("date") or form_data.get("date")
    only_missing_raw = qp.get("only_missing") if qp.get("only_missing") is not None else form_data.get("only_missing")
    only_missing = str(only_missing_raw).lower() in ("1", "true", "on") if only_missing_raw is not None else False
    eval_mode = str(form_data.get("eval_mode") or qp.get("eval_mode") or "diff").strip().lower()
    if eval_mode not in ("diff", "full"):
        eval_mode = "diff"
    sample_size_raw = form_data.get("sample_size") or qp.get("sample_size")
    sample_size = None
    if sample_size_raw and str(sample_size_raw).strip().isdigit():
        sample_size = int(sample_size_raw)

    if date:
        try:
            target_date = datetime.date.fromisoformat(str(date))
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="日期格式无效")
    else:
        target_date = _date.today()

    result = run_today(target_date, session=session, only_missing=only_missing, eval_mode=eval_mode,
                       sample_size=sample_size)

    if str(form_data.get("redirect", "")).lower() in ("1", "true"):
        return RedirectResponse(url=f"/results?date={target_date}", status_code=303)
    return result


@router.get("/projects/{project_id}/eval", response_class=HTMLResponse)
def project_eval_page(
    request: Request, project_id: int,
    auth_check=Depends(require_auth), session: Session = Depends(get_session),
):
    project, students = _load_project_ctx(session, project_id)
    plans = sorted(
        session.exec(select(DailyPlan).where(DailyPlan.project_id == project_id)).all(),
        key=lambda p: p.date, reverse=True,
    )
    return request.app.state.templates.TemplateResponse(request, "project_eval.html", {
        "project": project, "students": students, "plans": plans,
        "today": _date.today(),
    })


@router.post("/projects/{project_id}/run-eval")
def run_project_eval(
    project_id: int,
    auth_check=Depends(require_auth),
    date: str = Form(None),
    eval_mode: str = Form("diff"),
    only_missing: str = Form("0"),
    plan_id: str = Form(None),
    sample_size: str = Form(None),
    session: Session = Depends(get_session),
):
    if is_running():
        return JSONResponse({"busy": True, "error": "已有评测任务正在进行，请稍后再试"},
                            status_code=409)
    target_date = datetime.date.fromisoformat(date) if date else _date.today()
    pid = None
    if plan_id and str(plan_id).strip().isdigit():
        pid = int(plan_id)
        # 指定计划时，使用计划自身的日期（计划可能不是今天的）
        plan_row = session.get(DailyPlan, pid)
        if plan_row:
            target_date = plan_row.date
    sample = None
    if sample_size and str(sample_size).strip().isdigit():
        sample = int(sample_size)
    job_id = start_eval_job(
        target_date,
        project_id=project_id,
        only_missing=str(only_missing).lower() in ("1", "true", "on"),
        eval_mode=eval_mode if eval_mode in ("diff", "full") else "diff",
        plan_id=pid,
        sample_size=sample,
    )
    return JSONResponse({"job_id": job_id})


@router.get("/projects/{project_id}/plans")
def project_plans_for_date(
    project_id: int,
    auth_check=Depends(require_auth),
    date: str = None,
    session: Session = Depends(get_session),
):
    query = select(DailyPlan).where(DailyPlan.project_id == project_id)
    if date:
        query = query.where(DailyPlan.date == datetime.date.fromisoformat(date))
    query = query.order_by(DailyPlan.date.desc())
    plans = session.exec(query).all()
    return JSONResponse([{
        "id": p.id,
        "date": str(p.date),
        "content": p.content,
        "student_id": p.student_id,
    } for p in plans])


@router.get("/eval-progress/{job_id}")
def eval_progress(job_id: str, auth_check=Depends(require_auth)):
    from app.services.eval_jobs import get_job
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return JSONResponse(job)


@router.post("/projects/{project_id}/assessments/delete")
def delete_day_assessments(
    project_id: int,
    auth_check=Depends(require_auth),
    date: str = Form(...),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    target_date = datetime.date.fromisoformat(date)
    for a in session.exec(select(Assessment).where(
        Assessment.project_id == project_id, Assessment.date == target_date
    )).all():
        session.delete(a)
    session.commit()
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/assessments/{assessment_id}/delete")
def delete_single_assessment(
    project_id: int,
    assessment_id: int,
    auth_check=Depends(require_auth),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    assessment = session.get(Assessment, assessment_id)
    if assessment is None or assessment.project_id != project_id:
        raise HTTPException(status_code=404, detail="评测记录不存在")
    session.delete(assessment)
    session.commit()
    return RedirectResponse(url=f"/projects/{project_id}/assessments", status_code=303)


@router.post("/api/login", response_class=JSONResponse)
def login_endpoint_route(credentials=Depends(security)):
    return login_endpoint(credentials)
