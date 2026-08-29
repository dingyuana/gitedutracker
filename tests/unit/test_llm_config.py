import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
from sqlmodel import SQLModel, create_engine, Session


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class TestLlmConfigEffectiveSettings:

    def test_db_overrides_env(self, session):
        from app.services.settings_service import get_effective_settings, save_llm_config
        save_llm_config(
            session,
            llm_model="doubao-seed-1-6",
            llm_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_api_key="ak-test",
            llm_context_max_chars=8000,
        )
        s = get_effective_settings(session)
        assert s.llm_model == "doubao-seed-1-6"
        assert s.llm_base_url == "https://ark.cn-beijing.volces.com/api/v3"
        assert s.llm_api_key == "ak-test"
        assert s.llm_context_max_chars == 8000

    def test_blank_fields_keep_previous(self, session):
        from app.services.settings_service import save_llm_config, get_effective_settings
        save_llm_config(session, llm_model="model-a", llm_api_key="key-a")
        save_llm_config(session, llm_model="model-b", llm_api_key="")
        s = get_effective_settings(session)
        assert s.llm_model == "model-b"
        assert s.llm_api_key == "key-a"

    def test_no_db_row_falls_back_to_env(self, session):
        from app.services.settings_service import get_effective_settings
        from app.config import get_settings
        env = get_settings()
        s = get_effective_settings(session)
        assert s.llm_model == env.llm_model
        assert s.llm_base_url == env.llm_base_url

    def test_upsert_single_row(self, session):
        from sqlmodel import select
        from app.models import LlmConfig
        from app.services.settings_service import save_llm_config
        save_llm_config(session, llm_model="a")
        save_llm_config(session, llm_model="b")
        rows = session.exec(select(LlmConfig)).all()
        assert len(rows) == 1


class TestSmtpConfigEffectiveSettings:

    def test_db_overrides_env(self, session):
        from app.services.settings_service import get_effective_settings, save_smtp_config
        save_smtp_config(
            session,
            smtp_host="smtp.qq.com",
            smtp_port=465,
            smtp_user="user@qq.com",
            smtp_pass="auth-code",
            smtp_from="user@qq.com",
        )
        s = get_effective_settings(session)
        assert s.smtp_host == "smtp.qq.com"
        assert s.smtp_port == 465
        assert s.smtp_user == "user@qq.com"
        assert s.smtp_pass == "auth-code"
        assert s.smtp_from == "user@qq.com"

    def test_blank_fields_keep_previous(self, session):
        from app.services.settings_service import save_smtp_config, get_effective_settings
        save_smtp_config(session, smtp_host="smtp.qq.com", smtp_user="u@qq.com", smtp_pass="p1")
        save_smtp_config(session, smtp_host="smtp.163.com", smtp_user="", smtp_pass="")
        s = get_effective_settings(session)
        assert s.smtp_host == "smtp.163.com"
        assert s.smtp_user == "u@qq.com"
        assert s.smtp_pass == "p1"

    def test_no_db_row_falls_back_to_env(self, session):
        from app.services.settings_service import get_effective_settings
        from app.config import get_settings
        env = get_settings()
        s = get_effective_settings(session)
        assert s.smtp_host == env.smtp_host
        assert s.smtp_port == env.smtp_port

    def test_smtp_upsert_single_row(self, session):
        from sqlmodel import select
        from app.models import SmtpConfig
        from app.services.settings_service import save_smtp_config
        save_smtp_config(session, smtp_host="smtp.a.com", smtp_user="u1")
        save_smtp_config(session, smtp_host="smtp.b.com", smtp_user="u2")
        rows = session.exec(select(SmtpConfig)).all()
        assert len(rows) == 1

    def test_qq_email_auto_infers_host_port(self, session):
        from app.services.settings_service import save_smtp_config, get_effective_settings
        save_smtp_config(session, smtp_user="12345678@qq.com", smtp_pass="auth-code")
        s = get_effective_settings(session)
        assert s.smtp_host == "smtp.qq.com"
        assert s.smtp_port == 587
        assert s.smtp_user == "12345678@qq.com"
        assert s.smtp_from == "12345678@qq.com"

    def test_163_email_auto_infers_host_port(self, session):
        from app.services.settings_service import save_smtp_config, get_effective_settings
        save_smtp_config(session, smtp_user="user@163.com", smtp_pass="auth-code")
        s = get_effective_settings(session)
        assert s.smtp_host == "smtp.163.com"
        assert s.smtp_port == 587
        assert s.smtp_from == "user@163.com"

    def test_explicit_host_overrides_inference(self, session):
        from app.services.settings_service import save_smtp_config, get_effective_settings
        save_smtp_config(session, smtp_user="user@qq.com", smtp_pass="p",
                         smtp_host="custom.smtp.com", smtp_port=999)
        s = get_effective_settings(session)
        assert s.smtp_host == "custom.smtp.com"
        assert s.smtp_port == 999

    def test_placeholder_localhost_host_is_ignored_for_inference(self, session):
        from app.services.settings_service import save_smtp_config, get_effective_settings
        save_smtp_config(session, smtp_user="12345678@qq.com", smtp_pass="auth-code",
                         smtp_host="localhost", smtp_port=1025)
        s = get_effective_settings(session)
        assert s.smtp_host == "smtp.qq.com"
        assert s.smtp_port == 587

    def test_infer_smtp_settings_ignores_localhost(self):
        from app.services.settings_service import infer_smtp_settings
        host, port = infer_smtp_settings("user@163.com", explicit_host="localhost")
        assert host == "smtp.163.com"
        assert port == 587
        host, port = infer_smtp_settings("user@qq.com", explicit_host="custom.io", explicit_port=465)
        assert host == "custom.io"
        assert port == 465