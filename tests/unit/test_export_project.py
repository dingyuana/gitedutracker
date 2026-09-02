import sys
import os
import io
import pytest
import pandas as pd
from datetime import date
from sqlmodel import SQLModel, create_engine, Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.models import Student, Project, Assessment


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def session(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _insert_fixture(session):
    s1 = Student(name='张三', email='zs@example.com', github_repo='zs/repo')
    s2 = Student(name='李四', email='ls@example.com', github_repo='ls/repo')
    p1 = Project(name='项目A')
    session.add_all([s1, s2, p1])
    session.commit()

    assessments = [
        Assessment(student_id=s1.id, project_id=p1.id, date=date(2026, 8, 20),
                   quality_score=8.0, match_score=7.5, schedule_status='ontime',
                   total_score=7.8, comment='D1 张三评语', status='done'),
        Assessment(student_id=s2.id, project_id=p1.id, date=date(2026, 8, 20),
                   quality_score=6.0, match_score=6.5, schedule_status='behind',
                   total_score=6.3, comment='D1 李四评语', status='done'),
        Assessment(student_id=s1.id, project_id=p1.id, date=date(2026, 8, 21),
                   quality_score=9.0, match_score=8.5, schedule_status='ahead',
                   total_score=8.7, comment='D2 张三评语', status='done'),
        Assessment(student_id=s2.id, project_id=p1.id, date=date(2026, 8, 21),
                   quality_score=7.0, match_score=7.0, schedule_status='ontime',
                   total_score=7.0, comment='D2 李四评语', status='done'),
    ]
    session.add_all(assessments)
    session.commit()
    return s1, s2, p1


class TestExportProjectAssessments:

    def test_returns_bytes(self, session):
        _insert_fixture(session)
        from app.utils.export import export_project_assessments
        result = export_project_assessments(1, session=session)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_sheet_names_overview_then_dates(self, session):
        s1, s2, p1 = _insert_fixture(session)
        from app.utils.export import export_project_assessments
        result = export_project_assessments(p1.id, session=session)
        xl = pd.ExcelFile(io.BytesIO(result), engine='openpyxl')
        assert xl.sheet_names[0] == '分数总览'
        assert set(xl.sheet_names[1:]) == {'2026-08-20', '2026-08-21'}

    def test_overview_matrix_and_averages(self, session):
        s1, s2, p1 = _insert_fixture(session)
        from app.utils.export import export_project_assessments
        result = export_project_assessments(p1.id, session=session)
        df = pd.read_excel(io.BytesIO(result), sheet_name='分数总览',
                           index_col=0, engine='openpyxl')
        # 每名学生一行（含平均分列），另有「每日平均」行
        assert {'张三', '李四', '每日平均'} <= set(df.index)
        assert '平均分' in df.columns
        assert '2026-08-20' in df.columns
        assert '2026-08-21' in df.columns
        # 单元格 = 总分
        assert df.loc['张三', '2026-08-20'] == pytest.approx(7.8)
        assert df.loc['李四', '2026-08-21'] == pytest.approx(7.0)
        # 学生平均分
        assert df.loc['张三', '平均分'] == pytest.approx((7.8 + 8.7) / 2)
        assert df.loc['李四', '平均分'] == pytest.approx((6.3 + 7.0) / 2)
        # 每日平均
        assert df.loc['每日平均', '2026-08-20'] == pytest.approx((7.8 + 6.3) / 2)
        assert df.loc['每日平均', '2026-08-21'] == pytest.approx((8.7 + 7.0) / 2)
        # 全体平均角格
        assert df.loc['每日平均', '平均分'] == pytest.approx((7.8 + 6.3 + 8.7 + 7.0) / 4)

    def test_daily_sheet_columns_and_comment(self, session):
        s1, s2, p1 = _insert_fixture(session)
        from app.utils.export import export_project_assessments
        result = export_project_assessments(p1.id, session=session)
        df = pd.read_excel(io.BytesIO(result), sheet_name='2026-08-20',
                           engine='openpyxl')
        assert list(df.columns) == ['学生姓名', '质量分', '匹配分', '进度', '总分', '评语']
        assert len(df) == 2
        row = df[df['学生姓名'] == '张三'].iloc[0]
        assert row['质量分'] == pytest.approx(8.0)
        assert row['匹配分'] == pytest.approx(7.5)
        assert row['进度'] == 'ontime'
        assert row['总分'] == pytest.approx(7.8)
        assert row['评语'] == 'D1 张三评语'

    def test_excludes_non_done_assessments(self, session):
        s1, s2, p1 = _insert_fixture(session)
        pending = Assessment(student_id=s2.id, project_id=p1.id,
                             date=date(2026, 8, 22), status='pending',
                             total_score=5.0, comment='未完成')
        session.add(pending)
        session.commit()
        from app.utils.export import export_project_assessments
        result = export_project_assessments(p1.id, session=session)
        df = pd.read_excel(io.BytesIO(result), sheet_name='2026-08-21',
                           engine='openpyxl')
        assert len(df) == 2
        assert '未完成' not in df['评语'].tolist()
        xl = pd.ExcelFile(io.BytesIO(result), engine='openpyxl')
        assert '2026-08-22' not in xl.sheet_names

    def test_filters_by_project(self, session):
        s1, s2, p1 = _insert_fixture(session)
        p2 = Project(name='项目B')
        session.add(p2)
        session.commit()
        other = Assessment(student_id=s1.id, project_id=p2.id,
                           date=date(2026, 8, 22), total_score=9.9,
                           comment='别的项目', status='done')
        session.add(other)
        session.commit()
        from app.utils.export import export_project_assessments
        result = export_project_assessments(p1.id, session=session)
        xl = pd.ExcelFile(io.BytesIO(result), engine='openpyxl')
        assert '2026-08-22' not in xl.sheet_names

    def test_empty_project_creates_overview_with_headers_only(self, session):
        p1 = Project(name='空项目')
        session.add(p1)
        session.commit()
        from app.utils.export import export_project_assessments
        result = export_project_assessments(p1.id, session=session)
        xl = pd.ExcelFile(io.BytesIO(result), engine='openpyxl')
        assert xl.sheet_names == ['分数总览']
        df = pd.read_excel(io.BytesIO(result), sheet_name='分数总览',
                           engine='openpyxl')
        assert list(df.columns)[:2] == ['学生姓名', '平均分']