import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlmodel import SQLModel, create_engine, Session
from fastapi import Request, HTTPException
from starlette.datastructures import State


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def db_session(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def mock_settings_no_auth():
    from app.config import Settings
    s = Settings()
    s.admin_password = ""
    s.auto_run_time = ""
    s.llm_base_url = "https://api.openai.com/v1"
    s.llm_api_key = "sk-test"
    s.llm_model = "gpt-4o-mini"
    s.llm_context_max_chars = 12000
    return s


@pytest.fixture
def mock_settings_with_auth():
    from app.config import Settings
    s = Settings()
    s.admin_password = "testpass123"
    s.auto_run_time = "0 9 * * *"
    s.llm_base_url = "https://api.openai.com/v1"
    s.llm_api_key = "sk-test"
    s.llm_model = "gpt-4o-mini"
    s.llm_context_max_chars = 12000
    return s


def _make_mock_request(cookies: dict = None):
    mock_request = MagicMock(spec=Request)
    mock_request.cookies = cookies or {}
    mock_request.app = MagicMock()
    mock_request.app.state = State()
    return mock_request


class TestAuthMiddleware:

    def test_no_auth_when_password_empty(self, mock_settings_no_auth):
        """ADMIN_PASSWORD 为空时，所有请求直接通过"""
        with patch("app.middleware.auth.get_settings", return_value=mock_settings_no_auth):
            from app.middleware.auth import require_auth
            mock_request = _make_mock_request({})
            result = require_auth(mock_request)
            assert result is None

    def test_auth_required_when_password_set(self, mock_settings_with_auth):
        """ADMIN_PASSWORD 有值时，未登录请求返回 401"""
        with patch("app.middleware.auth.get_settings", return_value=mock_settings_with_auth):
            from app.middleware.auth import require_auth
            mock_request = _make_mock_request({})
            with pytest.raises(HTTPException) as exc_info:
                require_auth(mock_request)
            assert exc_info.value.status_code == 401

    def test_auth_pass_when_session_cookie_present(self, mock_settings_with_auth):
        """ADMIN_PASSWORD 有值且有 session cookie 时，请求通过"""
        with patch("app.middleware.auth.get_settings", return_value=mock_settings_with_auth):
            from app.middleware.auth import require_auth
            mock_request = _make_mock_request({"session": "some-token"})
            result = require_auth(mock_request)
            assert result is None

    def test_login_endpoint_returns_token(self, mock_settings_with_auth):
        """POST /api/login 使用正确密码返回 session cookie"""
        with patch("app.middleware.auth.get_settings", return_value=mock_settings_with_auth):
            from app.middleware.auth import login_endpoint
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            app = FastAPI()
            app.post("/api/login")(login_endpoint)
            client = TestClient(app, raise_server_exceptions=False)

            resp = client.post(
                "/api/login",
                json={"password": "testpass123"},
                auth=("user", "testpass123"),
            )
            assert resp.status_code == 200
            assert "session" in resp.cookies

    def test_login_endpoint_rejects_wrong_password(self, mock_settings_with_auth):
        """POST /api/login 使用错误密码返回 401"""
        with patch("app.middleware.auth.get_settings", return_value=mock_settings_with_auth):
            from app.middleware.auth import login_endpoint
            from fastapi import FastAPI
            from fastapi.testclient import TestClient

            app = FastAPI()
            app.post("/api/login")(login_endpoint)
            client = TestClient(app, raise_server_exceptions=False)

            resp = client.post(
                "/api/login",
                json={"password": "wrong"},
                auth=("user", "wrong"),
            )
            assert resp.status_code == 401


class TestScheduler:

    def test_starts_without_auto_run_time_but_skips_daily_job(self, mock_settings_no_auth):
        """AUTO_RUN_TIME 为空时仍须启动调度器（重试与定时计划 job 不依赖它），但不注册每日 cron"""
        import app.scheduler as scheduler_module
        scheduler_module._scheduler = None
        with patch.object(scheduler_module, "get_settings", return_value=mock_settings_no_auth):
            from app.scheduler import start_scheduler
            result = start_scheduler()
            try:
                assert result is not None
                ids = {j.id for j in result.get_jobs()}
                assert "run_today_daily" not in ids
                assert "retry_failed_assessments" in ids
                assert "run_due_schedules" in ids
            finally:
                result.shutdown(wait=False)
                scheduler_module._scheduler = None

    def test_scheduler_starts_when_auto_run_time_set(self, mock_settings_with_auth):
        """AUTO_RUN_TIME 有值时，start_scheduler 启动 APScheduler"""
        import app.scheduler as scheduler_module
        scheduler_module._scheduler = None
        with patch.object(scheduler_module, "get_settings", return_value=mock_settings_with_auth):
            with patch("app.scheduler.BackgroundScheduler") as MockScheduler:
                mock_scheduler_instance = MagicMock()
                MockScheduler.return_value = mock_scheduler_instance

                from app.scheduler import start_scheduler
                result = start_scheduler()

                MockScheduler.assert_called_once()
                assert mock_scheduler_instance.add_job.call_count == 3
                mock_scheduler_instance.start.assert_called_once()
                assert result is mock_scheduler_instance
        scheduler_module._scheduler = None

    def test_scheduler_adds_run_today_job(self, mock_settings_with_auth):
        """调度器添加的 job 调用 run_today"""
        import app.scheduler as scheduler_module
        scheduler_module._scheduler = None
        with patch.object(scheduler_module, "get_settings", return_value=mock_settings_with_auth):
            with patch("app.scheduler.BackgroundScheduler") as MockScheduler:
                mock_scheduler_instance = MagicMock()
                MockScheduler.return_value = mock_scheduler_instance

                from app.scheduler import start_scheduler
                start_scheduler()

                daily = [c for c in mock_scheduler_instance.add_job.call_args_list
                         if c[1].get("id") == "run_today_daily"]
                assert len(daily) == 1
                assert daily[0][0][1] == "cron"
        scheduler_module._scheduler = None
