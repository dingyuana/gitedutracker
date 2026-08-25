from sqlmodel import SQLModel, create_engine, Session
from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, echo=False)


def _migrate_sqlite():
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if 'student' in tables:
        cols = {c['name'] for c in inspector.get_columns('student')}
        if 'project_id' not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE student ADD COLUMN project_id INTEGER"))
        if 'student_no' not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE student ADD COLUMN student_no VARCHAR"))
    if 'project' in tables:
        cols = {c['name'] for c in inspector.get_columns('project')}
        if 'status' not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE project ADD COLUMN status VARCHAR DEFAULT 'active'"))


def init_db():
    # 确保模型已导入并注册到 SQLModel.metadata
    from app import models  # noqa: F401
    SQLModel.metadata.create_all(engine)
    _migrate_sqlite()


def get_session():
    with Session(engine) as session:
        yield session
