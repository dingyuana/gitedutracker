import datetime
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlmodel import Session, select

from app.database import get_session
from app.models import Student, Project, DailyPlan, Assessment, ScoringConfig
from app.utils.export import export_daily
from app.services.pipeline import run_today

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)):
    students = session.exec(select(Student)).all()
    projects = session.exec(select(Project)).all()
    latest_assessment = session.exec(
        select(Assessment)
        .order_by(Assessment.date.desc())
        .limit(1)
    ).first()
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "index.html", {
        "students": students,
        "projects": projects,
        "latest_assessment": latest_assessment,
    })


@router.get("/students", response_class=HTMLResponse)
def students_page(request: Request, session: Session = Depends(get_session)):
    student_list = session.exec(select(Student)).all()
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "students.html", {
        "students": student_list,
    })


@router.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, session: Session = Depends(get_session)):
    project_list = session.exec(select(Project)).all()
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "projects.html", {
        "projects": project_list,
    })


@router.get("/plans", response_class=HTMLResponse)
def plans_page(request: Request, session: Session = Depends(get_session)):
    plans = session.exec(
        select(DailyPlan).order_by(DailyPlan.date.desc())
    ).all()
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "plans.html", {
        "plans": plans,
    })


@router.get("/config", response_class=HTMLResponse)
def config_page(request: Request, session: Session = Depends(get_session)):
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
