from sqlmodel import SQLModel, create_engine, Session
from app.config import get_settings

settings = get_settings()

_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False} if _sqlite else {},
)

if _sqlite:
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def _migrate_sqlite():
    _migrate_sqlite_engine(engine)


def _migrate_sqlite_engine(engine):
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
    if 'assessment' in tables:
        cols = {c['name'] for c in inspector.get_columns('assessment')}
        if 'eval_type' not in cols:
            _rebuild_assessment_table(engine)
            cols = {c['name'] for c in inspect(engine).get_columns('assessment')}
        if 'fail_reason' not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE assessment ADD COLUMN fail_reason VARCHAR"))


def _rebuild_assessment_table(engine):
    """SQLite 无法 DROP sqlite_autoindex，需整表重建才能落地 (student_id, project_id, date, eval_type) 唯一约束。"""
    from sqlalchemy import inspect, text
    from sqlalchemy.schema import CreateTable
    from app.models import Assessment as _Assessment
    inspector = inspect(engine)
    old_cols = [c['name'] for c in inspector.get_columns('assessment')]
    new_cols = {c.name for c in _Assessment.__table__.columns}
    common = [c for c in old_cols if c in new_cols]
    common_sql = ", ".join(f'"{c}"' for c in common)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE assessment RENAME TO assessment_old"))
        conn.execute(CreateTable(_Assessment.__table__))
        conn.execute(text(
            f'INSERT INTO assessment ({common_sql}, eval_type) '
            f'SELECT {common_sql}, \'diff\' FROM assessment_old'
        ))
        conn.execute(text("DROP TABLE assessment_old"))


def init_db():
    # 确保模型已导入并注册到 SQLModel.metadata
    from app import models  # noqa: F401
    SQLModel.metadata.create_all(engine)
    _migrate_sqlite()


def get_session():
    with Session(engine) as session:
        yield session
