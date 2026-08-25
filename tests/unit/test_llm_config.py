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