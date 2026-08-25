import sys
import os
import pytest
import pandas as pd
from openpyxl import Workbook
from datetime import date
from sqlmodel import SQLModel, create_engine, Session, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.models import Student, Project, DailyPlan


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def session(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _write_xlsx(path: str, columns: list, rows: list) -> str:
    wb = Workbook()
    ws = wb.active
    ws.append(columns)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


class TestStudentImport:

    def test_import_students_basic(self, session, tmp_path):
        from app.services.import_service import import_students
        xlsx = str(tmp_path / "students.xlsx")
        _write_xlsx(xlsx, ['学生姓名', '邮箱', 'github仓库'], [
            ['张三', 'zhangsan@example.com', 'zhangsan/myrepo'],
            ['李四', 'lisi@example.com', 'https://github.com/lisi/project-x'],
            ['王五', 'wangwu@example.com', 'wangwu/hello-world'],
        ])
        count = import_students(xlsx, session=session)
        assert count == 3
        students = session.exec(select(Student)).all()
        assert len(students) == 3
        assert students[0].name == '张三'
        assert students[0].email == 'zhangsan@example.com'
        assert students[0].github_repo == 'zhangsan/myrepo'
        assert students[1].github_repo == 'lisi/project-x'

    def test_import_students_english_columns(self, session, tmp_path):
        from app.services.import_service import import_students
        xlsx = str(tmp_path / "students_en.xlsx")
        _write_xlsx(xlsx, ['student_name', 'email', 'github_repo', 'student_no'], [
            ['Alice', 'alice@test.com', 'alice/dev', '2024001'],
        ])
        count = import_students(xlsx, session=session)
        assert count == 1
        s = session.exec(select(Student)).first()
        assert s.name == 'Alice'

    def test_import_students_missing_email_raises(self, session, tmp_path):
        from app.services.import_service import import_students
        xlsx = str(tmp_path / "students_no_email.xlsx")
        _write_xlsx(xlsx, ['学生姓名', 'github仓库'], [
            ['张三', 'zhangsan/myrepo'],
        ])
        with pytest.raises(ValueError, match='邮箱'):
            import_students(xlsx, session=session)

    def test_import_students_empty_email_skips(self, session, tmp_path):
        from app.services.import_service import import_students
        xlsx = str(tmp_path / "students_empty_email.xlsx")
        _write_xlsx(xlsx, ['学生姓名', '邮箱', 'github仓库'], [
            ['张三', '', 'zhangsan/myrepo'],
        ])
        count = import_students(xlsx, session=session)
        assert count == 0

    def test_import_students_missing_required_column_raises(self, session, tmp_path):
        from app.services.import_service import import_students
        xlsx = str(tmp_path / "students_bad.xlsx")
        _write_xlsx(xlsx, ['姓名', '邮箱'], [
            ['张三', 'zhangsan@example.com'],
        ])
        with pytest.raises(ValueError, match='github仓库'):
            import_students(xlsx, session=session)

    def test_import_students_mixed_chinese_english_columns(self, session, tmp_path):
        from app.services.import_service import import_students
        xlsx = str(tmp_path / "students_mixed.xlsx")
        _write_xlsx(xlsx, ['学生姓名', 'github_repo', '邮箱'], [
            ['张三', 'zhangsan/repo', 'zhangsan@example.com'],
        ])
        count = import_students(xlsx, session=session)
        assert count == 1
        s = session.exec(select(Student)).first()
        assert s.name == '张三'
        assert s.github_repo == 'zhangsan/repo'


    def test_import_students_with_project_assignment(self, session, tmp_path):
        from app.services.import_service import import_students
        from app.models import Project
        p = Project(name='分组项目')
        session.add(p)
        session.commit()
        session.refresh(p)
        xlsx = str(tmp_path / "students_proj.xlsx")
        _write_xlsx(xlsx, ['姓名', '个人邮箱地址', 'github仓库地址'], [
            ['王五', 'ww@example.com', 'ww/myrepo'],
        ])
        count = import_students(xlsx, session=session, project_id=p.id)
        assert count == 1
        s = session.exec(select(Student)).first()
        assert s.project_id == p.id

    def test_reimport_reassigns_project_for_same_email(self, session, tmp_path):
        from app.services.import_service import import_students
        from app.models import Project
        p1 = Project(name='项目一')
        p2 = Project(name='项目二')
        session.add_all([p1, p2])
        session.commit()
        session.refresh(p1)
        session.refresh(p2)
        xlsx = str(tmp_path / "students_move.xlsx")
        _write_xlsx(xlsx, ['姓名', '邮箱', 'github仓库'], [
            ['赵六', 'zl@example.com', 'zl/myrepo'],
        ])
        import_students(xlsx, session=session, project_id=p1.id)
        import_students(xlsx, session=session, project_id=p2.id)
        students = session.exec(select(Student)).all()
        assert len(students) == 1
        assert students[0].project_id == p2.id


class TestProjectImport:

    def test_import_projects_basic(self, session, tmp_path):
        from app.services.import_service import import_projects
        xlsx = str(tmp_path / "projects.xlsx")
        _write_xlsx(xlsx, ['项目名称', '描述', '开始日期', '结束日期'], [
            ['Python入门', '学习Python基础', '2026-08-01', '2026-09-01'],
            ['数据分析', 'pandas入门', '2026-08-15', None],
        ])
        count = import_projects(xlsx, session=session)
        assert count == 2
        projects = session.exec(select(Project)).all()
        assert projects[0].name == 'Python入门'
        assert projects[0].description == '学习Python基础'
        assert projects[0].start_date == date(2026, 8, 1)
        assert projects[1].name == '数据分析'

    def test_import_projects_english_columns(self, session, tmp_path):
        from app.services.import_service import import_projects
        xlsx = str(tmp_path / "projects_en.xlsx")
        _write_xlsx(xlsx, ['project_name', 'description'], [
            ['Web开发', 'Flask基础'],
        ])
        count = import_projects(xlsx, session=session)
        assert count == 1
        p = session.exec(select(Project)).first()
        assert p.name == 'Web开发'
        assert p.description == 'Flask基础'

    def test_import_projects_missing_name_raises(self, session, tmp_path):
        from app.services.import_service import import_projects
        xlsx = str(tmp_path / "projects_no_name.xlsx")
        _write_xlsx(xlsx, ['描述'], [
            ['没有名字的项目'],
        ])
        with pytest.raises(ValueError, match='项目名称'):
            import_projects(xlsx, session=session)


class TestDailyPlanImport:

    def test_import_daily_plans_basic(self, session, tmp_path):
        from app.services.import_service import import_daily_plans, import_projects
        _write_xlsx(str(tmp_path / "projects.xlsx"), ['项目名称'], [
            ['Python入门'],
            ['数据分析'],
        ])
        import_projects(str(tmp_path / "projects.xlsx"), session=session)

        xlsx = str(tmp_path / "plans.xlsx")
        _write_xlsx(xlsx, ['日期', '项目名称', '工作计划', '学生姓名'], [
            ['2026-08-21', 'Python入门', '学习变量', '张三'],
            ['2026-08-21', '数据分析', '全员任务', None],
            ['2026-08-22', 'Python入门', '函数基础', '李四'],
        ])
        count = import_daily_plans(xlsx, session=session)
        assert count == 3
        plans = session.exec(select(DailyPlan)).all()
        assert len(plans) == 3
        assert plans[0].date == date(2026, 8, 21)
        assert plans[0].content == '学习变量'
        assert plans[0].student_id is None  # 张三 not in DB

    def test_import_daily_plans_all_students(self, session, tmp_path):
        from app.services.import_service import import_daily_plans, import_projects
        _write_xlsx(str(tmp_path / "projects.xlsx"), ['项目名称'], [
            ['Python入门'],
        ])
        import_projects(str(tmp_path / "projects.xlsx"), session=session)

        xlsx = str(tmp_path / "plans_all.xlsx")
        _write_xlsx(xlsx, ['日期', '项目名称', '工作计划'], [
            ['2026-08-21', 'Python入门', '全员阅读第一章'],
        ])
        count = import_daily_plans(xlsx, session=session)
        assert count == 1
        plan = session.exec(select(DailyPlan)).first()
        assert plan.student_id is None

    def test_import_daily_plans_missing_date_raises(self, session, tmp_path):
        from app.services.import_service import import_daily_plans
        xlsx = str(tmp_path / "plans_no_date.xlsx")
        _write_xlsx(xlsx, ['项目名称', '工作计划'], [
            ['Python入门', '学习'],
        ])
        with pytest.raises(ValueError, match='日期'):
            import_daily_plans(xlsx, session=session)

    def test_import_daily_plans_missing_project_raises(self, session, tmp_path):
        from app.services.import_service import import_daily_plans
        xlsx = str(tmp_path / "plans_no_project.xlsx")
        _write_xlsx(xlsx, ['日期', '工作计划'], [
            ['2026-08-21', '学习'],
        ])
        with pytest.raises(ValueError, match='项目名称'):
            import_daily_plans(xlsx, session=session)

    def test_import_daily_plans_project_not_found_raises(self, session, tmp_path):
        from app.services.import_service import import_daily_plans
        xlsx = str(tmp_path / "plans_bad_project.xlsx")
        _write_xlsx(xlsx, ['日期', '项目名称', '工作计划'], [
            ['2026-08-21', '不存在的项目', '学习'],
        ])
        with pytest.raises(ValueError, match='Python入门|不存在'):
            import_daily_plans(xlsx, session=session)


class TestColumnAliasMapping:

    def test_student_column_aliases(self):
        from app.services.import_service import STUDENT_COLUMN_ALIASES
        assert STUDENT_COLUMN_ALIASES['学生姓名'] == 'name'
        assert STUDENT_COLUMN_ALIASES['student_name'] == 'name'
        assert STUDENT_COLUMN_ALIASES['github仓库'] == 'github_repo'
        assert STUDENT_COLUMN_ALIASES['github_repo'] == 'github_repo'
        assert STUDENT_COLUMN_ALIASES['仓库地址'] == 'github_repo'
        assert STUDENT_COLUMN_ALIASES['邮箱'] == 'email'
        assert STUDENT_COLUMN_ALIASES['email'] == 'email'
        assert STUDENT_COLUMN_ALIASES['学号'] == 'student_no'
        assert STUDENT_COLUMN_ALIASES['student_no'] == 'student_no'

    def test_project_column_aliases(self):
        from app.services.import_service import PROJECT_COLUMN_ALIASES
        assert PROJECT_COLUMN_ALIASES['项目名称'] == 'name'
        assert PROJECT_COLUMN_ALIASES['project_name'] == 'name'
        assert PROJECT_COLUMN_ALIASES['描述'] == 'description'
        assert PROJECT_COLUMN_ALIASES['description'] == 'description'
        assert PROJECT_COLUMN_ALIASES['开始日期'] == 'start_date'
        assert PROJECT_COLUMN_ALIASES['start_date'] == 'start_date'
        assert PROJECT_COLUMN_ALIASES['结束日期'] == 'end_date'
        assert PROJECT_COLUMN_ALIASES['end_date'] == 'end_date'

    def test_plan_column_aliases(self):
        from app.services.import_service import PLAN_COLUMN_ALIASES
        assert PLAN_COLUMN_ALIASES['日期'] == 'date'
        assert PLAN_COLUMN_ALIASES['date'] == 'date'
        assert PLAN_COLUMN_ALIASES['项目名称'] == 'project_name'
        assert PLAN_COLUMN_ALIASES['project_name'] == 'project_name'
        assert PLAN_COLUMN_ALIASES['工作计划'] == 'content'
        assert PLAN_COLUMN_ALIASES['plan_content'] == 'content'
        assert PLAN_COLUMN_ALIASES['学生姓名'] == 'student_name'
        assert PLAN_COLUMN_ALIASES['student_name'] == 'student_name'

class TestStudentImportIdempotent:

    def test_reimport_same_email_updates_not_duplicates(self, session, tmp_path):
        from app.services.import_service import import_students
        xlsx = str(tmp_path / "students_update.xlsx")
        _write_xlsx(xlsx, ['学生姓名', '邮箱', 'github仓库'], [
            ['张三', 'zhangsan@example.com', 'zhangsan/myrepo'],
        ])
        assert import_students(xlsx, session=session) == 1

        _write_xlsx(xlsx, ['学生姓名', '邮箱', 'github仓库'], [
            ['张三', 'zhangsan@example.com', 'zhangsan/new-repo'],
        ])
        assert import_students(xlsx, session=session) == 1

        students = session.exec(select(Student)).all()
        assert len(students) == 1
        assert students[0].github_repo == 'zhangsan/new-repo'

    def test_import_students_persists_student_no(self, session, tmp_path):
        from app.services.import_service import import_students
        xlsx = str(tmp_path / "students_no.xlsx")
        _write_xlsx(xlsx, ['姓名', '个人邮箱地址', 'github仓库地址', '学号'], [
            ['钱七', 'qq@example.com', 'qq/myrepo', '25371007'],
        ])
        count = import_students(xlsx, session=session)
        assert count == 1
        s = session.exec(select(Student)).first()
        assert s.student_no == '25371007'

    def test_reimport_updates_student_no(self, session, tmp_path):
        from app.services.import_service import import_students
        xlsx = str(tmp_path / "students_no2.xlsx")
        _write_xlsx(xlsx, ['姓名', '个人邮箱地址', 'github仓库地址', '学号'], [
            ['孙八', 'sb@example.com', 'sb/myrepo', '111'],
        ])
        import_students(xlsx, session=session)
        _write_xlsx(xlsx, ['姓名', '个人邮箱地址', 'github仓库地址', '学号'], [
            ['孙八', 'sb@example.com', 'sb/myrepo', '222'],
        ])
        import_students(xlsx, session=session)
        s = session.exec(select(Student)).first()
        assert len(session.exec(select(Student)).all()) == 1
        assert s.student_no == '222'
