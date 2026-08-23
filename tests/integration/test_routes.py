import sys
import os
import json
import pytest
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlmodel import SQLModel, create_engine, Session, select
from app.models import (
    Student, Project, DailyPlan, GithubActivity, Assessment, ScoringConfig,
)


@pytest.fixture
def db_session(tmp_path):
    db_file = tmp_path / "test.db"
    eng = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    from sqlmodel import SQLModel
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture
def seed_data(db_session):
    s1 = Student(name='张三', email='zs@example.com', github_repo='zs/myrepo')
    s2 = Student(name='李四', email='ls@example.com', github_repo='ls/myrepo')
    db_session.add(s1)
    db_session.add(s2)
    db_session.commit()
    db_session.refresh(s1)
    db_session.refresh(s2)

    p1 = Project(name='项目A')
    db_session.add(p1)
    db_session.commit()
    db_session.refresh(p1)

    plan_all = DailyPlan(
        project_id=p1.id,
        date=date(2026, 8, 21),
        content='完成登录模块',
        student_id=None,
    )
    db_session.add(plan_all)
    db_session.commit()
    db_session.refresh(plan_all)

    config = ScoringConfig(
        w_volume=0.333, w_quality=0.333, w_match=0.333,
        loc_threshold=100, schedule_bonus=5.0, schedule_penalty=-5.0,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)

    target = date(2026, 8, 21)
    for s in [s1, s2]:
        activity = GithubActivity(
            student_id=s.id,
            date=target,
            commits_count=3,
            commits_json=json.dumps([
                {"sha": "abc123", "message": "feat: add login", "additions": 50, "deletions": 10}
            ], ensure_ascii=False),
            prs_opened=1,
            prs_merged=0,
            loc_additions=50,
            loc_deletions=10,
            status="ok",
        )
        db_session.add(activity)
    db_session.commit()

    return {
        's1': s1, 's2': s2, 'p1': p1,
        'plan_all': plan_all, 'config': config,
        'target': target,
    }


@pytest.fixture
def mock_settings():
    from app.config import Settings
    s = Settings()
    s.llm_base_url = "https://api.openai.com/v1"
    s.llm_api_key = "sk-test"
    s.llm_model = "gpt-4o-mini"
    s.llm_context_max_chars = 12000
    return s


@pytest.fixture
def mock_ai_response():
    return {
        "quality_score": 85,
        "match_score": 90,
        "completion": True,
        "schedule_status": "ontime",
        "comment": "表现良好，继续努力",
        "reasoning": "按时完成",
    }


@pytest.fixture
def app(db_session, mock_settings, mock_ai_response):
    import app.database as db_module
    db_module.engine = db_session.bind

    with patch("app.config._settings", mock_settings), \
         patch("app.services.pipeline.get_settings", return_value=mock_settings), \
         patch("app.services.pipeline.score_student", return_value=mock_ai_response), \
         patch("app.services.pipeline.sync_day", return_value=2), \
         patch("app.services.pipeline.send_daily_comments", return_value=None):
        from fastapi.templating import Jinja2Templates
        from app.main import app as fastapi_app
        fastapi_app.state.db_session = db_session
        fastapi_app.state.templates = Jinja2Templates(directory="app/templates")
        from fastapi.testclient import TestClient
        client = TestClient(fastapi_app)
        yield client


class TestGetIndex:

    def test_returns_200(self, app, db_session):
        resp = app.get("/")
        assert resp.status_code == 200

    def test_page_contains_run_today_button(self, app):
        resp = app.get("/")
        assert resp.status_code == 200
        assert "今日评测" in resp.text

    def test_page_shows_student_count(self, app, seed_data):
        resp = app.get("/")
        assert resp.status_code == 200
        assert "张三" in resp.text

    def test_page_shows_project_count(self, app, seed_data):
        resp = app.get("/")
        assert resp.status_code == 200
        assert "项目A" in resp.text


class TestGetStudents:

    def test_returns_200(self, app):
        resp = app.get("/students")
        assert resp.status_code == 200

    def test_shows_student_list(self, app, seed_data):
        resp = app.get("/students")
        assert resp.status_code == 200
        assert "张三" in resp.text
        assert "李四" in resp.text

    def test_contains_import_form(self, app):
        resp = app.get("/students")
        assert resp.status_code == 200
        assert "导入" in resp.text


class TestGetProjects:

    def test_returns_200(self, app):
        resp = app.get("/projects")
        assert resp.status_code == 200

    def test_shows_project_list(self, app, seed_data):
        resp = app.get("/projects")
        assert resp.status_code == 200
        assert "项目A" in resp.text


class TestGetPlans:

    def test_returns_200(self, app):
        resp = app.get("/plans")
        assert resp.status_code == 200

    def test_shows_plan_list(self, app, seed_data):
        resp = app.get("/plans")
        assert resp.status_code == 200
        assert "完成登录模块" in resp.text


class TestGetConfig:

    def test_returns_200(self, app):
        resp = app.get("/config")
        assert resp.status_code == 200

    def test_shows_weight_form(self, app):
        resp = app.get("/config")
        assert resp.status_code == 200
        assert "w_volume" in resp.text or "权重" in resp.text


class TestGetResults:

    def test_returns_200_with_date(self, app, seed_data):
        resp = app.get(f"/results?date={seed_data['target']}")
        assert resp.status_code == 200

    def test_shows_assessment_table(self, app, db_session, seed_data):
        from app.services.pipeline import run_today
        run_today(seed_data['target'], session=db_session)

        resp = app.get(f"/results?date={seed_data['target']}")
        assert resp.status_code == 200
        assert "张三" in resp.text

    def test_empty_date_returns_200(self, app):
        resp = app.get("/results?date=")
        assert resp.status_code == 200


class TestGetExport:

    def test_returns_200(self, app, seed_data):
        resp = app.get("/export", params={"date": str(seed_data['target']), "fmt": "xlsx"})
        assert resp.status_code == 200

    def test_returns_xlsx_bytes(self, app, seed_data):
        resp = app.get("/export", params={"date": str(seed_data['target']), "fmt": "xlsx"})
        assert resp.status_code == 200
        assert resp.content

    def test_content_disposition_attachment(self, app, seed_data):
        resp = app.get("/export", params={"date": str(seed_data['target']), "fmt": "xlsx"})
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd

    def test_invalid_fmt_returns_400(self, app, seed_data):
        resp = app.get("/export", params={"date": str(seed_data['target']), "fmt": "csv"})
        assert resp.status_code == 400


class TestPostRunToday:

    def test_returns_200(self, app):
        resp = app.post("/run-today", params={"date": "2026-08-21"})
        assert resp.status_code == 200

    def test_returns_summary(self, app, seed_data):
        resp = app.post("/run-today", params={"date": str(seed_data['target'])})
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert "failed" in data
        assert "details" in data

    def test_success_count_matches_students(self, app, seed_data):
        resp = app.post("/run-today", params={"date": str(seed_data['target'])})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] == 2

    def test_invalid_date_returns_422(self, app):
        resp = app.post("/run-today", params={"date": "not-a-date"})
        assert resp.status_code == 422


class TestPostStudentsImport:

    def _make_xlsx(self, tmp_path):
        from openpyxl import Workbook
        xlsx = str(tmp_path / "students.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.append(['学生姓名', '邮箱', 'github仓库'])
        for row in [['张三', 'zs@example.com', 'zs/myrepo'], ['李四', 'ls@example.com', 'ls/myrepo']]:
            ws.append(row)
        wb.save(xlsx)
        return xlsx

    def test_imports_students_from_xlsx(self, app, db_session, tmp_path):
        xlsx = self._make_xlsx(tmp_path)
        with open(xlsx, "rb") as f:
            resp = app.post("/students", files={"file": ("students.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert resp.status_code in (200, 302)
        from app.models import Student
        count = len(db_session.exec(select(Student)).all())
        assert count == 2

    def test_import_without_file_returns_422(self, app):
        resp = app.post("/students")
        assert resp.status_code == 422


class TestPostConfig:

    def test_updates_scoring_config(self, app, db_session, seed_data):
        resp = app.post("/config", data={
            "w_volume": "0.4",
            "w_quality": "0.3",
            "w_match": "0.3",
            "loc_threshold": "200",
            "schedule_bonus": "2.0",
            "schedule_penalty": "-3.0",
        })
        assert resp.status_code in (200, 302)
        cfg = db_session.exec(select(ScoringConfig)).first()
        assert cfg is not None
        assert abs(cfg.w_volume - 0.4) < 1e-6
        assert cfg.loc_threshold == 200
