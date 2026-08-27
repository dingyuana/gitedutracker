import sys
import os
import pytest
from datetime import date, datetime
from sqlmodel import SQLModel, create_engine, Session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.models import Student, Project, DailyPlan, GithubActivity, Assessment, ScoringConfig


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def session(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class TestStudent:

    def test_create_student_with_email(self, session):
        s = Student.model_validate({'name': '张三', 'email': 'zhangsan@example.com', 'github_repo': 'zhangsan/myrepo'})
        session.add(s)
        session.commit()
        session.refresh(s)
        assert s.id is not None
        assert s.name == '张三'
        assert s.email == 'zhangsan@example.com'
        assert s.github_repo == 'zhangsan/myrepo'

    def test_email_required(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            Student.model_validate({'name': '李四', 'github_repo': 'lisi/myrepo'})

    def test_github_repo_url_normalization(self):
        s = Student.model_validate({'name': '王五', 'email': 'wangwu@example.com', 'github_repo': 'https://github.com/wangwu/hello-world'})
        assert s.github_repo == 'wangwu/hello-world'

    def test_github_url_saved_for_github_url(self):
        s = Student.model_validate({'name': '王五', 'email': 'wangwu@example.com', 'github_repo': 'https://github.com/wangwu/hello-world'})
        assert s.github_url == 'https://github.com/wangwu/hello-world'

    def test_github_url_saved_for_gitee_url(self):
        s = Student.model_validate({'name': '钱七', 'email': 'qianqi@example.com', 'github_repo': 'https://gitee.com/qianqi/my-car'})
        assert s.github_repo == 'qianqi/my-car'
        assert s.github_url == 'https://gitee.com/qianqi/my-car'

    def test_github_url_none_for_owner_repo(self):
        s = Student.model_validate({'name': '赵六', 'email': 'zhaoliu@example.com', 'github_repo': 'zhaoliu/project-x'})
        assert s.github_url is None

    def test_github_repo_url_normalization_with_git_suffix(self):
        s = Student.model_validate({'name': '孙八', 'email': 'sunba@example.com', 'github_repo': 'https://gitee.com/sunba/car-project.git'})
        assert s.github_repo == 'sunba/car-project'
        assert s.github_url.endswith('car-project.git')

    def test_github_repo_owner_repo_format(self):
        s = Student.model_validate({'name': '赵六', 'email': 'zhaoliu@example.com', 'github_repo': 'zhaoliu/project-x'})
        assert s.github_repo == 'zhaoliu/project-x'

    def test_email_unique(self, session):
        session.add(Student.model_validate({'name': '学生A', 'email': 'a@example.com', 'github_repo': 'a/repo'}))
        session.commit()
        with pytest.raises(Exception):
            session.add(Student.model_validate({'name': '学生B', 'email': 'a@example.com', 'github_repo': 'b/repo'}))
            session.commit()


class TestProject:

    def test_create_project(self, session):
        p = Project(name="Python入门", description="学习Python基础", start_date=date(2026, 8, 1))
        session.add(p)
        session.commit()
        session.refresh(p)
        assert p.id is not None
        assert p.name == "Python入门"
        assert p.description == "学习Python基础"
        assert p.start_date == date(2026, 8, 1)
        assert p.end_date is None

    def test_project_nullable_fields(self, session):
        p = Project(name="速成项目")
        session.add(p)
        session.commit()
        session.refresh(p)
        assert p.description is None
        assert p.start_date is None
        assert p.end_date is None


class TestDailyPlan:

    def test_create_daily_plan_with_student(self, session):
        student = Student.model_validate({'name': '张三', 'email': 'zhangsan@example.com', 'github_repo': 'zhangsan/repo'})
        project = Project.model_validate({'name': 'Python入门'})
        session.add_all([student, project])
        session.commit()
        plan = DailyPlan.model_validate({'project_id': project.id, 'date': date(2026, 8, 21), 'content': '学习变量', 'student_id': student.id})
        session.add(plan)
        session.commit()
        session.refresh(plan)
        assert plan.id is not None
        assert plan.student_id == student.id

    def test_daily_plan_student_id_nullable(self, session):
        project = Project.model_validate({'name': 'Python入门'})
        session.add(project)
        session.commit()
        plan = DailyPlan.model_validate({'project_id': project.id, 'date': date(2026, 8, 21), 'content': '全员任务'})
        session.add(plan)
        session.commit()
        session.refresh(plan)
        assert plan.student_id is None


class TestGithubActivity:

    def test_create_activity(self, session):
        student = Student.model_validate({'name': '张三', 'email': 'zhangsan@example.com', 'github_repo': 'zhangsan/repo'})
        session.add(student)
        session.commit()
        activity = GithubActivity.model_validate({
            'student_id': student.id,
            'date': date(2026, 8, 21),
            'commits_count': 3,
            'prs_opened': 1,
            'prs_merged': 1,
            'loc_additions': 50,
            'loc_deletions': 10,
        })
        session.add(activity)
        session.commit()
        session.refresh(activity)
        assert activity.id is not None
        assert activity.status == 'pending'
        assert activity.commits_count == 3

    def test_default_values(self, session):
        student = Student.model_validate({'name': '张三', 'email': 'zhangsan@example.com', 'github_repo': 'zhangsan/repo'})
        session.add(student)
        session.commit()
        activity = GithubActivity.model_validate({'student_id': student.id, 'date': date(2026, 8, 21)})
        session.add(activity)
        session.commit()
        session.refresh(activity)
        assert activity.commits_count == 0
        assert activity.prs_opened == 0
        assert activity.prs_merged == 0
        assert activity.loc_additions == 0
        assert activity.loc_deletions == 0
        assert activity.status == 'pending'


class TestAssessment:

    def test_create_assessment_default_status(self, session):
        student = Student.model_validate({'name': '张三', 'email': 'zhangsan@example.com', 'github_repo': 'zhangsan/repo'})
        project = Project.model_validate({'name': 'Python入门'})
        session.add_all([student, project])
        session.commit()
        a = Assessment.model_validate({'student_id': student.id, 'project_id': project.id, 'date': date(2026, 8, 21)})
        session.add(a)
        session.commit()
        session.refresh(a)
        assert a.status == 'pending'
        assert a.attempts == 0
        assert a.email_sent is False

    def test_assessment_unique_constraint(self, session):
        student = Student.model_validate({'name': '张三', 'email': 'zhangsan@example.com', 'github_repo': 'zhangsan/repo'})
        project = Project.model_validate({'name': 'Python入门'})
        session.add_all([student, project])
        session.commit()
        a1 = Assessment.model_validate({'student_id': student.id, 'project_id': project.id, 'date': date(2026, 8, 21)})
        session.add(a1)
        session.commit()
        with pytest.raises(Exception):
            a2 = Assessment.model_validate({'student_id': student.id, 'project_id': project.id, 'date': date(2026, 8, 21)})
            session.add(a2)
            session.commit()


class TestScoringConfig:

    def test_default_values(self):
        c = ScoringConfig()
        assert c.w_volume == 0.333
        assert c.w_quality == 0.333
        assert c.w_match == 0.333
        assert c.loc_threshold == 100
        assert c.schedule_bonus == 5.0
        assert c.schedule_penalty == -5.0

    def test_create_and_persist(self, session):
        c = ScoringConfig.model_validate({'w_volume': 0.3, 'w_quality': 0.4, 'w_match': 0.3})
        session.add(c)
        session.commit()
        session.refresh(c)
        assert c.w_volume == 0.3
        assert c.w_quality == 0.4
        assert c.w_match == 0.3
