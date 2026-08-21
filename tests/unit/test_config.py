import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def _write_env(tmpdir, content):
    env_path = os.path.join(tmpdir, '.env')
    with open(env_path, 'w') as f:
        f.write(content)
    return env_path


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch, tmpdir):
    import app.config
    monkeypatch.setattr(app.config, '_settings', None)
    monkeypatch.setattr(app.config, '_engine', None)
    monkeypatch.chdir(tmpdir)


class TestSettings:

    def test_load_from_env(self, tmpdir, monkeypatch):
        env_content = (
            'GITHUB_TOKEN=ghp_testtoken\n'
            'LLM_BASE_URL=https://api.example.com/v1\n'
            'LLM_API_KEY=sk_testkey\n'
            'LLM_MODEL=gpt-4\n'
            'LLM_CONTEXT_MAX_CHARS=15000\n'
            'SMTP_HOST=smtp.office365.com\n'
            'SMTP_PORT=587\n'
            'SMTP_USER=test@office.com\n'
            'SMTP_PASS=testpass\n'
            'SMTP_FROM=test@office.com\n'
            'ADMIN_PASSWORD=secret123\n'
            'AUTO_RUN_TIME=0 9 * * *\n'
            'DATABASE_URL=sqlite:///./test.db\n'
            'TZ=Asia/Shanghai\n'
        )
        _write_env(tmpdir, env_content)
        monkeypatch.chdir(tmpdir)

        from app.config import get_settings
        s = get_settings()

        assert s.github_token == 'ghp_testtoken'
        assert s.llm_base_url == 'https://api.example.com/v1'
        assert s.llm_api_key == 'sk_testkey'
        assert s.llm_model == 'gpt-4'
        assert s.llm_context_max_chars == 15000
        assert s.smtp_host == 'smtp.office365.com'
        assert s.smtp_port == 587
        assert s.smtp_user == 'test@office.com'
        assert s.smtp_pass == 'testpass'
        assert s.smtp_from == 'test@office.com'
        assert s.admin_password == 'secret123'
        assert s.auto_run_time == '0 9 * * *'
        assert s.database_url == 'sqlite:///./test.db'
        assert s.tz == 'Asia/Shanghai'

    def test_defaults(self, tmpdir, monkeypatch):
        _write_env(tmpdir, '')
        monkeypatch.chdir(tmpdir)

        from app.config import get_settings
        s = get_settings()

        assert s.llm_base_url == 'https://api.openai.com/v1'
        assert s.llm_model == 'gpt-4o-mini'
        assert s.llm_context_max_chars == 12000
        assert s.smtp_host == 'smtp.gmail.com'
        assert s.smtp_port == 587
        assert s.tz == 'Asia/Shanghai'
        assert s.database_url == 'sqlite:///./data/github_tracker.db'
        assert s.github_token == ''
        assert s.llm_api_key == ''
        assert s.admin_password == ''
        assert s.auto_run_time == ''

    def test_singleton(self, tmpdir, monkeypatch):
        _write_env(tmpdir, 'TZ=Asia/Shanghai\n')
        monkeypatch.chdir(tmpdir)

        from app.config import get_settings
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_require_auth_false_when_empty(self, tmpdir, monkeypatch):
        _write_env(tmpdir, '')
        monkeypatch.chdir(tmpdir)

        from app.config import get_settings
        s = get_settings()
        assert s.require_auth is False

    def test_require_auth_true_when_set(self, tmpdir, monkeypatch):
        _write_env(tmpdir, 'ADMIN_PASSWORD=mysecret\n')
        monkeypatch.chdir(tmpdir)

        from app.config import get_settings
        s = get_settings()
        assert s.require_auth is True

    def test_missing_llm_api_key_no_exception(self, tmpdir, monkeypatch):
        _write_env(tmpdir, 'GITHUB_TOKEN=ghp_x\n')
        monkeypatch.chdir(tmpdir)

        from app.config import get_settings
        s = get_settings()
        assert s.llm_api_key == ''

    def test_init_db_creates_tables(self, tmpdir, monkeypatch):
        _write_env(tmpdir, 'DATABASE_URL=sqlite:///./test_init.db\n')
        monkeypatch.chdir(tmpdir)

        from app.config import init_db
        init_db()

        import os
        assert os.path.exists(os.path.join(tmpdir, 'test_init.db'))

    def test_init_db_with_explicit_url(self, tmpdir, monkeypatch):
        from app.config import init_db
        import os

        db_path = os.path.join(tmpdir, 'test_explicit.db')
        init_db(f'sqlite:///{db_path}')

        assert os.path.exists(db_path)
