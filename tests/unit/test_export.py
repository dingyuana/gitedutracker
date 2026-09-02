import sys
import os
import io
import pytest
import pandas as pd
from datetime import date
from sqlmodel import SQLModel, create_engine, Session, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.models import Student, Project, Assessment, GithubActivity


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def session(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _insert_fixture_data(session):
    student = Student(name='张三', email='zhangsan@example.com', github_repo='zhangsan/myproject')
    project = Project(name='Python入门')
    session.add_all([student, project])
    session.commit()

    activity = GithubActivity(
        student_id=student.id,
        date=date(2026, 8, 21),
        loc_additions=50,
        loc_deletions=10,
    )
    session.add(activity)
    session.commit()

    assessment = Assessment(
        student_id=student.id,
        project_id=project.id,
        date=date(2026, 8, 21),
        quality_score=8.5,
        match_score=7.0,
        total_score=7.8,
        schedule_status='ontime',
        comment='表现良好',
        status='done',
    )
    session.add(assessment)
    session.commit()
    return student.id, project.id


class TestExportDaily:

    def test_returns_bytes(self, session):
        _insert_fixture_data(session)
        from app.utils.export import export_daily
        result = export_daily(date(2026, 8, 21), session=session)
        assert isinstance(result, bytes)

    def test_no_data_returns_empty_xlsx_with_correct_headers(self, session):
        from app.utils.export import export_daily
        result = export_daily(date(2026, 8, 21), session=session)
        assert isinstance(result, bytes)
        df = pd.read_excel(io.BytesIO(result), engine='openpyxl')
        expected_cols = [
            '日期', '学生姓名', '邮箱', 'GitHub仓库', '项目名称',
            '代码增', '代码删', '代码量分', '质量分', '匹配分', '加分',
            '进度状态', '进度调整', '总分', '评语'
        ]
        assert list(df.columns) == expected_cols
        assert len(df) == 0

    def test_columns_order(self, session):
        _insert_fixture_data(session)
        from app.utils.export import export_daily
        result = export_daily(date(2026, 8, 21), session=session)
        df = pd.read_excel(io.BytesIO(result), engine='openpyxl')
        expected_cols = [
            '日期', '学生姓名', '邮箱', 'GitHub仓库', '项目名称',
            '代码增', '代码删', '代码量分', '质量分', '匹配分', '加分',
            '进度状态', '进度调整', '总分', '评语'
        ]
        assert list(df.columns) == expected_cols

    def test_row_values_correct(self, session):
        _insert_fixture_data(session)
        from app.utils.export import export_daily
        result = export_daily(date(2026, 8, 21), session=session)
        df = pd.read_excel(io.BytesIO(result), engine='openpyxl')
        assert len(df) == 1
        row = df.iloc[0]
        assert row['日期'] == '2026-08-21'
        assert row['学生姓名'] == '张三'
        assert row['邮箱'] == 'zhangsan@example.com'
        assert row['GitHub仓库'] == 'zhangsan/myproject'
        assert row['项目名称'] == 'Python入门'
        assert row['代码增'] == 50
        assert row['代码删'] == 10
        assert row['质量分'] == 8.5
        assert row['匹配分'] == 7.0
        assert row['进度状态'] == '正常'
        assert row['总分'] == 7.8
        assert row['评语'] == '表现良好'

    def test_filters_by_date(self, session):
        _insert_fixture_data(session)

        student = Student(name='李四', email='lisi@example.com', github_repo='lisi/another')
        project = Project(name='Java入门')
        session.add_all([student, project])
        session.commit()

        activity = GithubActivity(
            student_id=student.id,
            date=date(2026, 8, 22),
            loc_additions=30,
            loc_deletions=5,
        )
        session.add(activity)
        session.commit()

        assessment = Assessment(
            student_id=student.id,
            project_id=project.id,
            date=date(2026, 8, 22),
            quality_score=6.0,
            match_score=5.5,
            total_score=5.8,
            schedule_status='behind',
            comment='需努力',
            status='done',
        )
        session.add(assessment)
        session.commit()

        from app.utils.export import export_daily
        result = export_daily(date(2026, 8, 21), session=session)
        df = pd.read_excel(io.BytesIO(result), engine='openpyxl')
        assert len(df) == 1
        assert df.iloc[0]['学生姓名'] == '张三'

        result2 = export_daily(date(2026, 8, 22), session=session)
        df2 = pd.read_excel(io.BytesIO(result2), engine='openpyxl')
        assert len(df2) == 1
        assert df2.iloc[0]['学生姓名'] == '李四'

    def test_excludes_non_done_assessments(self, session):
        _insert_fixture_data(session)

        # Add a pending assessment for a different project on the same date
        student = session.exec(
            select(Student).where(Student.email == 'zhangsan@example.com')
        ).one()
        other_project = Project(name='进阶项目')
        session.add(other_project)
        session.commit()

        pending = Assessment(
            student_id=student.id,
            project_id=other_project.id,
            date=date(2026, 8, 21),
            status='pending',
        )
        session.add(pending)
        session.commit()

        from app.utils.export import export_daily
        result = export_daily(date(2026, 8, 21), session=session)
        df = pd.read_excel(io.BytesIO(result), engine='openpyxl')
        assert len(df) == 1
        assert df.iloc[0]['学生姓名'] == '张三'


class TestAllScoreDimensionsExported:

    def test_zero_scores_render_as_zero_not_blank(self, session):
        from app.models import Student, Project, Assessment
        from app.utils.export import export_daily
        s = Student(name='零分生', email='z@e.com', github_repo='z/r')
        p = Project(name='项目Z')
        session.add_all([s, p])
        session.commit()
        session.refresh(s)
        session.refresh(p)
        session.add(Assessment(
            student_id=s.id, project_id=p.id, date=date(2026, 8, 21),
            status='done', volume_score=0.0, quality_score=0.0,
            match_score=0.0, bonus_score=0.0, schedule_adjustment=0.0,
            total_score=0.0, schedule_status='behind', comment='c',
        ))
        session.commit()

        df = pd.read_excel(io.BytesIO(export_daily(date(2026, 8, 21), session=session)),
                           engine='openpyxl')
        row = df.iloc[0]
        assert row['代码量分'] == 0.0
        assert row['加分'] == 0.0
        assert row['进度调整'] == 0.0
        assert row['进度状态'] == '滞后'

    def test_schedule_status_translated_to_chinese(self, session):
        from app.models import Student, Project, Assessment
        from app.utils.export import export_daily
        s = Student(name='超前生', email='a@e.com', github_repo='a/r')
        p = Project(name='项目A')
        session.add_all([s, p])
        session.commit()
        session.refresh(s)
        session.refresh(p)
        session.add(Assessment(
            student_id=s.id, project_id=p.id, date=date(2026, 8, 21),
            status='done', schedule_status='ahead', schedule_adjustment=5.0,
            volume_score=90.0, total_score=95.0,
        ))
        session.commit()

        df = pd.read_excel(io.BytesIO(export_daily(date(2026, 8, 21), session=session)),
                           engine='openpyxl')
        assert df.iloc[0]['进度状态'] == '超前'
        assert df.iloc[0]['进度调整'] == 5.0
