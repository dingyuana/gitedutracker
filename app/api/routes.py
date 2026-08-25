import datetime
import tempfile
from datetime import date as _date
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from sqlmodel import Session, select

from app.database import get_session
from app.models import Student, Project, DailyPlan, Assessment, ScoringConfig
from app.utils.export import export_daily
from app.services.import_service import import_students
from app.services.pipeline import run_today
from app.middleware.auth import require_auth, login_endpoint, security

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request, auth_check=Depends(require_auth), session: Session = Depends(get_session)):
    today = _date.today()
    projects = session.exec(select(Project)).all()

    cards = []
    for p in projects:
        if p.start_date and today < p.start_date:
            day_label = "未开始"
        elif p.start_date and p.end_date and today > p.end_date:
            day_label = "已结束"
        elif p.start_date:
            day_n = (today - p.start_date).days + 1
            day_label = f"第{day_n}天"
            if p.end_date:
                total_days = (p.end_date - p.start_date).days + 1
                day_label += f" / 共{total_days}天"
        else:
            day_label = "未排期"

        plans_today = session.exec(
            select(DailyPlan).where(DailyPlan.project_id == p.id, DailyPlan.date == today)
        ).all()
        assessed_today = session.exec(
            select(Assessment).where(Assessment.project_id == p.id, Assessment.date == today)
        ).all()
        done_today = [a for a in assessed_today if a.status == "done"]

        cards.append({
            "project": p,
            "day_label": day_label,
            "plan_count": len(plans_today),
            "plan_summary": plans_today[0].content if plans_today else None,
            "assessed_count": len(done_today),
        })

    templates = request.app.state.templates
    return templates.TemplateResponse(request, "index.html", {
        "cards": cards,
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
def projects_page(request: Request, auth_check=Depends(require_auth), session: Session = Depends(get_session)):
    project_list = session.exec(select(Project)).all()
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "projects.html", {
        "projects": project_list,
    })


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
    return RedirectResponse(url="/projects", status_code=303)


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
    return RedirectResponse(url="/projects", status_code=303)


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
    return RedirectResponse(url="/projects", status_code=303)


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
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "config.html", {
        "config": config,
    })


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
def run_today_endpoint(
    auth_check=Depends(require_auth),
    date: str = None,
    session: Session = Depends(get_session),
):
    if not date:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="缺少 date 参数")
    try:
        target_date = datetime.date.fromisoformat(date)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="日期格式无效")
    result = run_today(target_date, session=session)
    return result


@router.post("/api/login", response_class=JSONResponse)
def login_endpoint_route(credentials=Depends(security)):
    return login_endpoint(credentials)
