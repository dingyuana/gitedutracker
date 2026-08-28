import sys
import os
import json
import pytest
from datetime import date, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlmodel import SQLModel, create_engine, Session, select, delete
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

    s1.project_id = p1.id
    s2.project_id = p1.id
    db_session.add(s1)
    db_session.add(s2)
    db_session.commit()

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
         patch("app.services.pipeline.get_effective_settings", return_value=mock_settings), \
         patch("app.services.pipeline.score_student", return_value=mock_ai_response), \
         patch("app.services.pipeline.sync_day", return_value=2), \
         patch("app.services.pipeline.send_daily_comments", return_value=None), \
         patch("app.services.pipeline.extract_day_activity",
               return_value={"commits_count": 1, "loc_additions": 5, "loc_deletions": 1,
                             "code_diffs": []}), \
         patch("app.services.pipeline.extract_snapshot",
               return_value={"files": [{"path": "main.py", "content": "print(1)", "truncated": False}]}):
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
        assert "eval-btn" in resp.text

    def test_page_hides_student_details(self, app, seed_data):
        resp = app.get("/")
        assert resp.status_code == 200
        assert "张三" not in resp.text
        assert "李四" not in resp.text

    def test_page_shows_project_status_card(self, app, seed_data):
        resp = app.get("/")
        assert resp.status_code == 200
        assert "项目A" in resp.text
        # 无起止日期 → 未排期；有日期 → 第N天/未开始/已结束
        assert ("未排期" in resp.text) or ("第" in resp.text)

    def test_page_shows_project_day_progress(self, app, db_session, seed_data):
        p = db_session.get(Project, seed_data['p1'].id)
        today = date.today()
        p.start_date = today - timedelta(days=4)
        p.end_date = today + timedelta(days=95)
        db_session.add(p)
        db_session.commit()
        resp = app.get("/")
        assert resp.status_code == 200
        assert "第5天" in resp.text
        assert "共100天" in resp.text


class TestGetStudents:

    def test_returns_200(self, app):
        resp = app.get("/students")
        assert resp.status_code == 200

    def test_shows_student_list(self, app, seed_data):
        resp = app.get("/students")
        assert resp.status_code == 200
        assert "张三" in resp.text
        assert "李四" in resp.text

    def test_students_page_shows_project_column(self, app, seed_data):
        resp = app.get("/students")
        assert resp.status_code == 200
        assert "所属项目" in resp.text

    def test_students_page_import_form_has_project_select(self, app, seed_data):
        resp = app.get("/students")
        assert 'name="project_id"' in resp.text

    def test_contains_import_form(self, app):
        resp = app.get("/students")
        assert resp.status_code == 200
        assert "导入" in resp.text


class TestGetProjects:

    def test_redirects_to_home(self, app):
        resp = app.get("/projects", follow_redirects=False)
        assert resp.status_code in (301, 302, 303, 307)
        assert "/" in resp.headers["location"]

    def test_home_shows_project_card(self, app, seed_data):
        resp = app.get("/")
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

    def test_without_date_defaults_to_today(self, app):
        resp = app.post("/run-today")
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data
        assert "failed" in data

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

    def test_form_submit_redirects_to_results(self, app, seed_data):
        resp = app.post("/run-today", data={
            "date": str(seed_data['target']),
            "only_missing": "0",
            "redirect": "1",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert f"/results?date={seed_data['target']}" in resp.headers["location"]

    def test_index_has_eval_panel_controls(self, app):
        resp = app.get("/")
        assert 'id="eval-scope-input"' in resp.text
        assert "仅未测评" in resp.text
        assert "全部重新评测" in resp.text
        assert 'type="date"' in resp.text
        assert 'id="eval-mode-input"' in resp.text

    def test_only_missing_passed_to_pipeline(self, app, db_session):
        with patch("app.api.routes.run_today") as mock_run:
            mock_run.return_value = {"success": 0, "failed": 0, "details": []}
            app.post("/run-today", data={"date": "2026-08-21", "only_missing": "1"})
            _, kwargs = mock_run.call_args
            assert kwargs.get("only_missing") is True

    def test_eval_mode_passed_to_pipeline(self, app):
        with patch("app.api.routes.run_today") as mock_run:
            mock_run.return_value = {"success": 0, "failed": 0, "details": []}
            app.post("/run-today", data={"date": "2026-08-21", "eval_mode": "full"})
            _, kwargs = mock_run.call_args
            assert kwargs.get("eval_mode") == "full"

    def test_index_panel_has_eval_mode_select(self, app):
        resp = app.get("/")
        assert 'id="eval-mode-input"' in resp.text
        assert "当日变更评审" in resp.text
        assert "全项目代码审核" in resp.text

    def test_project_eval_endpoint_starts_job(self, app, seed_data):
        with patch("app.api.routes.start_eval_job") as mock_start:
            mock_start.return_value = "job123"
            resp = app.post(f"/projects/{seed_data['p1'].id}/run-eval", data={
                "date": str(seed_data['target']),
                "eval_mode": "full",
                "only_missing": "0",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job123"
        _, args, kwargs = mock_start.mock_calls[0]
        assert kwargs.get("project_id") == seed_data['p1'].id
        assert kwargs.get("eval_mode") == "full"

    def test_project_eval_endpoint_passes_plan_id(self, app, seed_data):
        with patch("app.api.routes.start_eval_job") as mock_start:
            mock_start.return_value = "job123"
            resp = app.post(f"/projects/{seed_data['p1'].id}/run-eval", data={
                "date": str(seed_data['target']),
                "eval_mode": "diff",
                "only_missing": "0",
                "plan_id": str(seed_data['plan_all'].id),
            })
        assert resp.status_code == 200
        _, args, kwargs = mock_start.mock_calls[0]
        assert kwargs.get("plan_id") == seed_data['plan_all'].id

    def test_project_eval_uses_plan_date_when_plan_id_set(self, app, seed_data):
        plan_date = seed_data['plan_all'].date
        other_date = date(2026, 12, 31)
        with patch("app.api.routes.start_eval_job") as mock_start:
            mock_start.return_value = "job123"
            resp = app.post(f"/projects/{seed_data['p1'].id}/run-eval", data={
                "date": str(other_date),
                "eval_mode": "diff",
                "only_missing": "0",
                "plan_id": str(seed_data['plan_all'].id),
            })
        assert resp.status_code == 200
        _, args, kwargs = mock_start.mock_calls[0]
        assert kwargs["plan_id"] == seed_data['plan_all'].id
        assert args[0] == plan_date

    def test_project_eval_blank_plan_id_passes_none(self, app, seed_data):
        with patch("app.api.routes.start_eval_job") as mock_start:
            mock_start.return_value = "job123"
            app.post(f"/projects/{seed_data['p1'].id}/run-eval", data={
                "date": str(seed_data['target']),
                "plan_id": "",
            })
        _, args, kwargs = mock_start.mock_calls[0]
        assert kwargs.get("plan_id") is None

    def test_project_eval_endpoint_passes_sample_size(self, app, seed_data):
        with patch("app.api.routes.start_eval_job") as mock_start:
            mock_start.return_value = "job123"
            resp = app.post(f"/projects/{seed_data['p1'].id}/run-eval", data={
                "date": str(seed_data['target']),
                "eval_mode": "diff",
                "only_missing": "1",
                "sample_size": "5",
            })
        assert resp.status_code == 200
        _, args, kwargs = mock_start.mock_calls[0]
        assert kwargs.get("sample_size") == 5

    def test_run_eval_rejects_when_job_running(self, app, seed_data):
        with patch("app.api.routes.is_running", return_value=True), \
             patch("app.api.routes.start_eval_job") as mock_start:
            resp = app.post(f"/projects/{seed_data['p1'].id}/run-eval", data={
                "date": str(seed_data['target']),
                "eval_mode": "diff",
                "only_missing": "0",
            })
        assert resp.status_code == 409
        assert resp.json()["busy"] is True
        mock_start.assert_not_called()

    def test_run_today_rejects_when_job_running(self, app):
        with patch("app.api.routes.is_running", return_value=True), \
             patch("app.api.routes.run_today") as mock_run:
            resp = app.post("/run-today", params={"date": "2026-08-21"})
        assert resp.status_code == 409
        assert resp.json()["busy"] is True
        mock_run.assert_not_called()

    def test_project_eval_page_lists_all_plans_in_picker(self, app, seed_data):
        resp = app.get(f"/projects/{seed_data['p1'].id}/eval")
        assert resp.status_code == 200
        assert "完成登录模块" in resp.text
        assert "全部计划" in resp.text
        assert 'name="plan" value="' + str(seed_data['plan_all'].id) + '"' in resp.text
        assert 'name="content"' in resp.text

    def test_project_eval_page_has_quick_add_plan_form(self, app, seed_data):
        resp = app.get(f"/projects/{seed_data['p1'].id}/eval")
        assert 'action="/plans" method="POST"' in resp.text
        assert f'value="{seed_data["p1"].id}"' in resp.text
        assert 'name="date"' in resp.text

    def test_project_eval_nonexistent_project_returns_404(self, app):
        assert app.get("/projects/9999/eval").status_code == 404

    def test_project_plans_endpoint_returns_plans_for_date(self, app, seed_data):
        resp = app.get(
            f"/projects/{seed_data['p1'].id}/plans?date={seed_data['target']}",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["content"] == "完成登录模块"
        assert data[0]["date"] == str(seed_data['target'])

    def test_project_plans_endpoint_empty_without_date(self, app, seed_data):
        resp = app.get(
            f"/projects/{seed_data['p1'].id}/plans",
            headers={"Accept": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1

    def test_eval_progress_endpoint(self, app):
        import app.services.eval_jobs as ej
        ej._jobs["testjob"] = {"job_id": "testjob", "status": "running",
                               "done": 3, "total": 10, "current": "张三"}
        try:
            resp = app.get("/eval-progress/testjob")
            assert resp.status_code == 200
            data = resp.json()
            assert data["done"] == 3
            assert data["total"] == 10
            assert data["current"] == "张三"
        finally:
            ej._jobs.pop("testjob", None)

    def test_eval_progress_unknown_job_404(self, app):
        assert app.get("/eval-progress/nonexistent").status_code == 404


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

    def test_import_with_project_assignment(self, app, db_session, tmp_path, seed_data):
        xlsx = self._make_xlsx(tmp_path)
        pid = seed_data['p1'].id
        with open(xlsx, "rb") as f:
            resp = app.post("/students", data={"project_id": str(pid)}, files={"file": ("students.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert resp.status_code in (200, 302, 303)
        db_session.expire_all()
        students = db_session.exec(select(Student)).all()
        assert len(students) == 2
        for s in students:
            assert s.project_id == pid


class TestPostConfig:

    def test_config_page_shows_llm_section(self, app):
        resp = app.get("/config")
        assert resp.status_code == 200
        assert "LLM 设置" in resp.text
        assert 'name="llm_model"' in resp.text
        assert 'action="/config/llm"' in resp.text

    def test_config_page_shows_smtp_section(self, app):
        resp = app.get("/config")
        assert resp.status_code == 200
        assert "邮件发送设置" in resp.text
        assert 'name="smtp_host"' in resp.text
        assert 'name="smtp_port"' in resp.text
        assert 'action="/config/smtp"' in resp.text

    def test_post_smtp_config_saves(self, app, db_session):
        from app.models import SmtpConfig
        resp = app.post("/config/smtp", data={
            "smtp_host": "smtp.qq.com",
            "smtp_port": "465",
            "smtp_user": "sender@qq.com",
            "smtp_pass": "auth-code-123",
            "smtp_from": "sender@qq.com",
        })
        assert resp.status_code in (200, 302, 303)
        db_session.expire_all()
        row = db_session.get(SmtpConfig, 1)
        assert row is not None
        assert row.smtp_host == "smtp.qq.com"
        assert row.smtp_port == 465
        assert row.smtp_user == "sender@qq.com"
        assert row.smtp_pass == "auth-code-123"

    def test_post_blank_smtp_password_keeps_old(self, app, db_session):
        from app.models import SmtpConfig
        app.post("/config/smtp", data={
            "smtp_host": "smtp.a.com", "smtp_port": "587",
            "smtp_user": "u1@a.com", "smtp_pass": "secret-1", "smtp_from": "u1@a.com",
        })
        app.post("/config/smtp", data={
            "smtp_host": "smtp.b.com", "smtp_port": "",
            "smtp_user": "u2@b.com", "smtp_pass": "", "smtp_from": "",
        })
        db_session.expire_all()
        row = db_session.get(SmtpConfig, 1)
        assert row.smtp_host == "smtp.b.com"
        assert row.smtp_user == "u2@b.com"
        assert row.smtp_pass == "secret-1"

    def test_post_llm_config_saves(self, app, db_session):
        from app.models import LlmConfig
        resp = app.post("/config/llm", data={
            "llm_model": "doubao-seed-1-6",
            "llm_base_url": "https://ark.example.com/api/v3",
            "llm_api_key": "ak-123",
            "llm_context_max_chars": "9000",
        })
        assert resp.status_code in (200, 302, 303)
        db_session.expire_all()
        row = db_session.get(LlmConfig, 1)
        assert row is not None
        assert row.llm_model == "doubao-seed-1-6"
        assert row.llm_api_key == "ak-123"
        assert row.llm_context_max_chars == 9000

    def test_post_blank_api_key_keeps_old(self, app, db_session):
        from app.models import LlmConfig
        app.post("/config/llm", data={
            "llm_model": "m1", "llm_base_url": "https://x/v1",
            "llm_api_key": "real-key", "llm_context_max_chars": "",
        })
        app.post("/config/llm", data={
            "llm_model": "m2", "llm_base_url": "", "llm_api_key": "",
            "llm_context_max_chars": "",
        })
        db_session.expire_all()
        row = db_session.get(LlmConfig, 1)
        assert row.llm_model == "m2"
        assert row.llm_api_key == "real-key"

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


class TestPostCreateProject:

    def test_creates_project(self, app, db_session):
        resp = app.post("/projects", data={
            "name": "新项目B",
            "description": "测试项目",
            "start_date": "2026-09-01",
            "end_date": "2026-12-31",
        })
        assert resp.status_code in (200, 302)
        projects = db_session.exec(select(Project)).all()
        assert any(p.name == "新项目B" for p in projects)
        created = [p for p in projects if p.name == "新项目B"][0]
        assert created.description == "测试项目"
        assert str(created.start_date) == "2026-09-01"
        assert str(created.end_date) == "2026-12-31"

    def test_creates_project_without_optional_fields(self, app, db_session):
        resp = app.post("/projects", data={"name": "最小项目"})
        assert resp.status_code in (200, 302)
        projects = db_session.exec(select(Project)).all()
        assert any(p.name == "最小项目" for p in projects)

    def test_missing_name_returns_422(self, app):
        resp = app.post("/projects", data={})
        assert resp.status_code == 422


class TestPostCreatePlan:

    def test_creates_plan(self, app, db_session, seed_data):
        resp = app.post("/plans", data={
            "date": "2026-08-24",
            "project_id": str(seed_data['p1'].id),
            "content": "实现新功能",
            "student_id": "",
        })
        assert resp.status_code in (200, 302)
        plans = db_session.exec(select(DailyPlan)).all()
        assert any(p.content == "实现新功能" for p in plans)
        created = [p for p in plans if p.content == "实现新功能"][0]
        assert str(created.date) == "2026-08-24"
        assert created.project_id == seed_data['p1'].id
        assert created.student_id is None

    def test_creates_plan_for_specific_student(self, app, db_session, seed_data):
        resp = app.post("/plans", data={
            "date": "2026-08-24",
            "project_id": str(seed_data['p1'].id),
            "content": "张三专属任务",
            "student_id": str(seed_data['s1'].id),
        })
        assert resp.status_code in (200, 302)
        plans = db_session.exec(select(DailyPlan)).all()
        created = [p for p in plans if p.content == "张三专属任务"][0]
        assert created.student_id == seed_data['s1'].id

    def test_missing_content_returns_422(self, app, seed_data):
        resp = app.post("/plans", data={"date": "2026-08-24", "project_id": str(seed_data['p1'].id)})
        assert resp.status_code == 422


class TestPageHasCreateForms:

    def test_home_page_has_create_project_form(self, app):
        resp = app.get("/")
        assert resp.status_code == 200
        assert "新建项目" in resp.text
        assert 'action="/projects" method="POST"' in resp.text

    def test_plans_page_has_create_form(self, app, seed_data):
        resp = app.get("/plans")
        assert resp.status_code == 200
        assert "新增计划" in resp.text
        assert 'action="/plans" method="POST"' in resp.text


class TestProjectDetail:

    def test_detail_returns_200_with_name(self, app, seed_data):
        resp = app.get(f"/projects/{seed_data['p1'].id}")
        assert resp.status_code == 200
        assert "项目A" in resp.text

    def test_detail_shows_project_plans(self, app, seed_data):
        resp = app.get(f"/projects/{seed_data['p1'].id}")
        assert "完成登录模块" in resp.text

    def test_detail_shows_assessment_scores_and_comments(self, app, db_session, seed_data):
        a = Assessment(
            student_id=seed_data['s1'].id,
            project_id=seed_data['p1'].id,
            date=seed_data['target'],
            total_score=88.5,
            comment="今日完成了登录模块，代码质量良好",
            status="done",
        )
        db_session.add(a)
        db_session.commit()
        resp = app.get(f"/projects/{seed_data['p1'].id}/assessments")
        assert resp.status_code == 200
        assert "张三" in resp.text
        assert "88.5" in resp.text
        assert "今日完成了登录模块" in resp.text

    def test_detail_nonexistent_returns_404(self, app):
        assert app.get("/projects/9999").status_code == 404

    def test_detail_shows_score_trend_charts(self, app, db_session, seed_data):
        from datetime import timedelta
        t = seed_data['target']
        for i, score in enumerate([60, 88]):
            db_session.add(Assessment(
                student_id=seed_data['s1'].id,
                project_id=seed_data['p1'].id,
                date=t + timedelta(days=i),
                total_score=score,
                comment="评语",
                status="done",
            ))
        db_session.commit()
        resp = app.get(f"/projects/{seed_data['p1'].id}/charts")
        assert resp.status_code == 200
        assert "分数趋势" in resp.text or "分数变化" in resp.text
        assert "<svg" in resp.text

    def test_detail_has_add_plan_form_bound_to_project(self, app, seed_data):
        resp = app.get(f"/projects/{seed_data['p1'].id}/plans")
        assert 'action="/plans" method="POST"' in resp.text
        assert f'value="{seed_data["p1"].id}"' in resp.text


class TestProjectComplete:

    def test_complete_marks_done(self, app, db_session, seed_data):
        pid = seed_data['p1'].id
        resp = app.post(f"/projects/{pid}/complete")
        assert resp.status_code in (200, 302, 303)
        db_session.expire_all()
        assert db_session.get(Project, pid).status == "done"

    def test_completed_project_in_done_section_on_home(self, app, db_session, seed_data):
        pid = seed_data['p1'].id
        app.post(f"/projects/{pid}/complete")
        resp = app.get("/")
        assert "已完成" in resp.text
        assert "项目A" in resp.text

    def test_reopen_restores_active(self, app, db_session, seed_data):
        pid = seed_data['p1'].id
        app.post(f"/projects/{pid}/complete")
        resp = app.post(f"/projects/{pid}/reopen")
        assert resp.status_code in (200, 302, 303)
        db_session.expire_all()
        assert db_session.get(Project, pid).status == "active"

    def test_complete_nonexistent_returns_404(self, app):
        assert app.post("/projects/9999/complete").status_code == 404


class TestProjectManagement:

    def test_home_has_edit_delete_complete_buttons(self, app, seed_data):
        resp = app.get("/")
        assert resp.status_code == 200
        assert "编辑" in resp.text
        assert "删除" in resp.text
        assert "完成" in resp.text

    def test_edit_page_returns_200(self, app, seed_data):
        resp = app.get(f"/projects/{seed_data['p1'].id}/edit")
        assert resp.status_code == 200
        assert "项目A" in resp.text

    def test_edit_updates_project(self, app, db_session, seed_data):
        pid = seed_data['p1'].id
        resp = app.post(f"/projects/{pid}/edit", data={
            "name": "项目A-改",
            "description": "新描述",
            "start_date": "2026-09-01",
            "end_date": "",
        })
        assert resp.status_code in (200, 302)
        db_session.expire_all()
        updated = db_session.get(Project, pid)
        assert updated.name == "项目A-改"
        assert updated.description == "新描述"
        assert str(updated.start_date) == "2026-09-01"

    def test_edit_missing_name_returns_422(self, app, seed_data):
        resp = app.post(f"/projects/{seed_data['p1'].id}/edit", data={"description": "x"})
        assert resp.status_code == 422

    def test_edit_nonexistent_returns_404(self, app):
        resp = app.get("/projects/9999/edit")
        assert resp.status_code == 404

    def test_delete_removes_project(self, app, db_session, seed_data):
        pid = seed_data['p1'].id
        resp = app.post(f"/projects/{pid}/delete")
        assert resp.status_code in (200, 302)
        db_session.expire_all()
        assert db_session.get(Project, pid) is None

    def test_delete_cascades_plans(self, app, db_session, seed_data):
        pid = seed_data['p1'].id
        app.post(f"/projects/{pid}/delete")
        plans = db_session.exec(select(DailyPlan)).all()
        assert all(p.project_id != pid for p in plans)

    def test_delete_nonexistent_returns_404(self, app):
        resp = app.post("/projects/9999/delete")
        assert resp.status_code == 404


class TestPlanManagement:

    def test_list_has_edit_delete_buttons(self, app, seed_data):
        resp = app.get("/plans")
        assert resp.status_code == 200
        assert "编辑" in resp.text
        assert "删除" in resp.text

    def test_edit_page_returns_200(self, app, seed_data):
        resp = app.get(f"/plans/{seed_data['plan_all'].id}/edit")
        assert resp.status_code == 200
        assert "完成登录模块" in resp.text

    def test_edit_updates_plan(self, app, db_session, seed_data):
        plan_id = seed_data['plan_all'].id
        resp = app.post(f"/plans/{plan_id}/edit", data={
            "date": "2026-08-22",
            "project_id": str(seed_data['p1'].id),
            "content": "完成登录模块-改",
            "student_id": str(seed_data['s1'].id),
        })
        assert resp.status_code in (200, 302)
        db_session.expire_all()
        updated = db_session.get(DailyPlan, plan_id)
        assert updated.content == "完成登录模块-改"
        assert str(updated.date) == "2026-08-22"
        assert updated.student_id == seed_data['s1'].id

    def test_edit_nonexistent_returns_404(self, app):
        resp = app.get("/plans/9999/edit")
        assert resp.status_code == 404

    def test_delete_removes_plan(self, app, db_session, seed_data):
        plan_id = seed_data['plan_all'].id
        resp = app.post(f"/plans/{plan_id}/delete")
        assert resp.status_code in (200, 302)
        db_session.expire_all()
        assert db_session.get(DailyPlan, plan_id) is None

    def test_delete_nonexistent_returns_404(self, app):
        resp = app.post("/plans/9999/delete")
        assert resp.status_code == 404


class TestPostStudentUpdate:

    def test_updates_name_email_and_repo(self, app, db_session, seed_data):
        sid = seed_data['s1'].id
        pid = seed_data['p1'].id
        resp = app.post(f"/students/{sid}/update", data={
            "name": "张三丰",
            "email": "zhangsanfeng@example.com",
            "github_repo": "zs3/repo-new",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/projects/{pid}/students"
        db_session.expire_all()
        s = db_session.get(Student, sid)
        assert s.name == "张三丰"
        assert s.email == "zhangsanfeng@example.com"
        assert s.github_repo == "zs3/repo-new"

    def test_update_full_url_sets_github_url(self, app, db_session, seed_data):
        sid = seed_data['s1'].id
        resp = app.post(f"/students/{sid}/update", data={
            "name": "张三",
            "email": "zs@example.com",
            "github_repo": "https://gitee.com/zs/gitee-car",
        }, follow_redirects=False)
        assert resp.status_code == 303
        db_session.expire_all()
        s = db_session.get(Student, sid)
        assert s.github_repo == "zs/gitee-car"
        assert s.github_url == "https://gitee.com/zs/gitee-car"

    def test_update_owner_repo_clears_github_url(self, app, db_session, seed_data):
        sid = seed_data['s1'].id
        db_session.get(Student, sid).github_url = "https://github.com/zs/myrepo"
        db_session.commit()
        resp = app.post(f"/students/{sid}/update", data={
            "name": "张三",
            "email": "zs@example.com",
            "github_repo": "zs/myrepo",
        }, follow_redirects=False)
        assert resp.status_code == 303
        db_session.expire_all()
        s = db_session.get(Student, sid)
        assert s.github_repo == "zs/myrepo"
        assert s.github_url is None

    def test_update_email_conflict_returns_400(self, app, db_session, seed_data):
        sid = seed_data['s1'].id
        resp = app.post(f"/students/{sid}/update", data={
            "name": "张三",
            "email": "ls@example.com",  # 李四已占用
            "github_repo": "zs/myrepo",
        }, follow_redirects=False)
        assert resp.status_code == 400
        db_session.expire_all()
        s = db_session.get(Student, sid)
        assert s.email == "zs@example.com"  # 未变更

    def test_update_nonexistent_returns_404(self, app):
        resp = app.post("/students/9999/update", data={
            "name": "x", "email": "x@example.com", "github_repo": "x/repo",
        }, follow_redirects=False)
        assert resp.status_code == 404

    def test_project_students_page_has_edit_buttons(self, app, seed_data):
        pid = seed_data['p1'].id
        resp = app.get(f"/projects/{pid}/students")
        assert resp.status_code == 200
        assert f"/students/{seed_data['s1'].id}/update" in resp.text
        assert "编辑" in resp.text


class TestStudentsPageDisplay:

    def test_shows_total_count(self, app, seed_data):
        resp = app.get("/students")
        assert resp.status_code == 200
        assert "共 2 名学生" in resp.text

    def test_table_has_index_column(self, app, seed_data):
        resp = app.get("/students")
        assert "<th>#</th>" in resp.text
        assert "<td>1</td>" in resp.text
        assert "<td>2</td>" in resp.text

    def test_table_has_student_no_column(self, app, seed_data):
        resp = app.get("/students")
        assert "<th>学号</th>" in resp.text


class TestDeleteDayAssessments:

    def _seed_two_days(self, db_session, seed_data):
        from datetime import timedelta
        t = seed_data['target']
        for i, sc in enumerate([70, 80]):
            db_session.add(Assessment(student_id=seed_data['s1'].id, project_id=seed_data['p1'].id,
                                      date=t + timedelta(days=i), total_score=sc, status="done"))
        db_session.commit()
        return t

    def test_deletes_only_target_date(self, app, db_session, seed_data):
        from datetime import timedelta
        t = self._seed_two_days(db_session, seed_data)
        resp = app.post(f"/projects/{seed_data['p1'].id}/assessments/delete",
                        data={"date": str(t)})
        assert resp.status_code in (200, 302, 303)
        db_session.expire_all()
        left = db_session.exec(select(Assessment).where(
            Assessment.project_id == seed_data['p1'].id)).all()
        assert len(left) == 1
        assert left[0].date == t + timedelta(days=1)

    def test_detail_page_has_day_delete_button(self, app, db_session, seed_data):
        t = self._seed_two_days(db_session, seed_data)
        resp = app.get(f"/projects/{seed_data['p1'].id}/assessments")
        assert "/assessments/delete" in resp.text
        assert f'value="{t}"' in resp.text

    def test_nonexistent_project_returns_404(self, app):
        assert app.post("/projects/9999/assessments/delete",
                        data={"date": "2026-08-26"}).status_code == 404


class TestDeleteSingleAssessment:

    def _seed_two(self, db_session, seed_data):
        from datetime import timedelta
        t = seed_data['target']
        a1 = Assessment(student_id=seed_data['s1'].id, project_id=seed_data['p1'].id,
                        date=t, total_score=70, status="done")
        a2 = Assessment(student_id=seed_data['s2'].id, project_id=seed_data['p1'].id,
                        date=t, total_score=80, status="done")
        db_session.add_all([a1, a2])
        db_session.commit()
        db_session.refresh(a1)
        db_session.refresh(a2)
        return a1, a2

    def test_deletes_only_specified_assessment(self, app, db_session, seed_data):
        a1, a2 = self._seed_two(db_session, seed_data)
        a1_id = a1.id
        a2_id = a2.id
        resp = app.post(f"/projects/{seed_data['p1'].id}/assessments/{a1_id}/delete",
                        follow_redirects=False)
        assert resp.status_code == 303
        db_session.expire_all()
        assert db_session.get(Assessment, a1_id) is None
        assert db_session.get(Assessment, a2_id) is not None

    def test_delete_nonexistent_assessment_returns_404(self, app, seed_data):
        resp = app.post(f"/projects/{seed_data['p1'].id}/assessments/9999/delete",
                        follow_redirects=False)
        assert resp.status_code == 404

    def test_delete_nonexistent_project_returns_404(self, app, seed_data):
        resp = app.post("/projects/9999/assessments/9999/delete", follow_redirects=False)
        assert resp.status_code == 404

    def test_assessments_page_has_per_row_delete_button(self, app, db_session, seed_data):
        a1, a2 = self._seed_two(db_session, seed_data)
        resp = app.get(f"/projects/{seed_data['p1'].id}/assessments")
        assert resp.status_code == 200
        assert f"/assessments/{a1.id}/delete" in resp.text
        assert f"/assessments/{a2.id}/delete" in resp.text


class TestClearStudents:

    def _seed_for_clear(self, db_session, seed_data):
        s3 = Student(name='王五', email='ww@example.com', github_repo='ww/car',
                     project_id=None)
        db_session.add(s3)
        db_session.commit()
        db_session.refresh(s3)

        from datetime import date
        t = seed_data['target']
        for sid in [seed_data['s1'].id, seed_data['s2'].id]:
            db_session.add(Assessment(student_id=sid, project_id=seed_data['p1'].id,
                                      date=t, total_score=80, status="done"))
        db_session.add(DailyPlan(project_id=seed_data['p1'].id, date=t,
                                 content='给s1的plan', student_id=seed_data['s1'].id))
        db_session.add(DailyPlan(project_id=seed_data['p1'].id, date=t+timedelta(days=1),
                                 content='给s2的plan', student_id=seed_data['s2'].id))
        db_session.add(DailyPlan(project_id=seed_data['p1'].id, date=t+timedelta(days=1),
                                 content='给s3的plan', student_id=s3.id))
        db_session.commit()
        return s3

    def test_clear_project_students_cascades(self, app, db_session, seed_data):
        s3 = self._seed_for_clear(db_session, seed_data)
        pid = seed_data['p1'].id
        before_students = db_session.exec(select(Student).where(Student.project_id == pid)).all()
        assert len(before_students) == 2
        before_asmt = db_session.exec(
            select(Assessment).where(Assessment.project_id == pid)).all()
        before_act = db_session.exec(
            select(GithubActivity).where(GithubActivity.student_id.in_(
                [s.id for s in before_students]))).all()
        before_plans = db_session.exec(
            select(DailyPlan).where(DailyPlan.project_id == pid)).all()
        assert len(before_asmt) == 2
        assert len(before_act) == 2
        assert len(before_plans) == 4

        # 在 expire_all 前保存所有 ID（expire_all 会使 seed_data 对象过期）
        pid = seed_data['p1'].id
        s1_id = seed_data['s1'].id
        s2_id = seed_data['s2'].id
        s3_id = 3

        resp = app.post(f"/projects/{pid}/students/clear",
                        data={}, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/projects/{pid}/students"

        db_session.expire_all()
        remaining = db_session.exec(select(Student).where(Student.project_id == pid)).all()
        assert len(remaining) == 0
        assert db_session.get(Student, s3_id) is not None

        left_asmt = db_session.exec(select(Assessment)).all()
        assert len(left_asmt) == 0

        left_act = db_session.exec(select(GithubActivity)).all()
        assert len(left_act) == 0

        left_plans = db_session.exec(select(DailyPlan).where(
            DailyPlan.project_id == pid)).all()
        # s1/s2 的 plan 学生引用已清空；s3 的 plan 保留（s3 不属于该项目）
        s1_s2_plans = [p for p in left_plans if p.student_id in (s1_id, s2_id)]
        assert len(s1_s2_plans) == 0
        s3_plans = [p for p in left_plans if p.student_id == s3_id]
        assert len(s3_plans) == 1

    def test_clear_all_students_globs(self, app, db_session, seed_data):
        self._seed_for_clear(db_session, seed_data)
        before = len(db_session.exec(select(Student)).all())
        assert before == 3
        resp = app.post("/students/clear", data={}, follow_redirects=False)
        assert resp.status_code == 303
        db_session.expire_all()
        assert len(db_session.exec(select(Student)).all()) == 0
        assert len(db_session.exec(select(Assessment)).all()) == 0
        assert len(db_session.exec(select(GithubActivity)).all()) == 0
        plans = db_session.exec(select(DailyPlan)).all()
        assert all(p.student_id is None for p in plans)

    def test_clear_project_nonexistent_returns_404(self, app):
        resp = app.post("/projects/9999/students/clear", data={},
                        follow_redirects=False)
        assert resp.status_code == 404

    def test_clear_all_nonexistent_students_is_ok(self, app, db_session):
        resp = app.post("/students/clear", data={}, follow_redirects=False)
        assert resp.status_code in (200, 302, 303)

    def test_project_students_page_has_clear_button(self, app, seed_data):
        resp = app.get(f"/projects/{seed_data['p1'].id}/students")
        assert resp.status_code == 200
        assert "清空全部" in resp.text

    def test_students_page_has_clear_button(self, app):
        resp = app.get("/students")
        assert resp.status_code == 200
        assert "清空全部" in resp.text
