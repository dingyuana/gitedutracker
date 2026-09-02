"""全项目综合评测（eval_mode='full'）测试：TDD RED 先行。

覆盖：
- full 模式每学生一条 Assessment（eval_type='full'），跳过 GitHub 同步
- 计划聚合语义（含专属/全体计划、排除未来日期/他生专属）
- bonus（超出设计要求加分）计入总分并落库 bonus_score
- 幂等（重跑更新不重复）
- only_missing 按 eval_type 隔离（diff done 不阻塞 full）
- 无历史计划的学生跳过
- 迁移：旧 schema assessment 表重建加 eval_type/bonus_score，数据保留
- AI 评分 full 分支：必填字段校验 + bonus 越界拒绝 + 使用 full system prompt
"""

import json
import sys
import os
from datetime import date
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from sqlmodel import SQLModel, create_engine, Session, select
from app.models import (
    Student, Project, DailyPlan, Assessment, ScoringConfig,
)
from app.services.scoring_engine import compute_final


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def session(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def seed_full(session):
    """项目 A + 2 学生 + 混合计划（含未来日期与专属计划）。"""
    p1 = Project(name='项目A')
    session.add(p1)
    session.commit()
    session.refresh(p1)

    s1 = Student(name='张三', email='zs@example.com', github_repo='zs/myrepo', project_id=p1.id)
    s2 = Student(name='李四', email='ls@example.com', github_repo='ls/myrepo', project_id=p1.id)
    s3 = Student(name='王五', email='ww@example.com', github_repo='ww/norepo')  # 无项目
    session.add_all([s1, s2, s3])
    session.commit()
    for s in [s1, s2, s3]:
        session.refresh(s)

    session.add(ScoringConfig(
        w_volume=0.333, w_quality=0.333, w_match=0.333,
        loc_threshold=100, schedule_bonus=5.0, schedule_penalty=-5.0,
    ))

    target = date(2026, 8, 21)
    plans = [
        DailyPlan(project_id=p1.id, date=date(2026, 8, 20), content='第一天：搭建项目骨架', student_id=None),
        DailyPlan(project_id=p1.id, date=target, content='第二天：完成登录模块', student_id=None),
        DailyPlan(project_id=p1.id, date=target, content='第二天：登录模块（张三专属）', student_id=s1.id),
        DailyPlan(project_id=p1.id, date=date(2026, 8, 22), content='未来：还没到日期的任务', student_id=None),
        DailyPlan(project_id=p1.id, date=date(2026, 8, 19), content='第一天：李四专属任务', student_id=s2.id),
    ]
    session.add_all(plans)
    session.commit()
    for p in plans:
        session.refresh(p)

    return {'p1': p1, 's1': s1, 's2': s2, 's3': s3, 'target': target, 'plans': plans}


@pytest.fixture
def mock_settings():
    from app.config import Settings
    s = Settings()
    s.llm_base_url = "https://api.openai.com/v1"
    s.llm_api_key = "sk-test"
    s.llm_model = "gpt-4o-mini"
    s.llm_context_max_chars = 12000
    return s


@pytest.fixture
def full_ai_response():
    return {
        "quality_score": 85,
        "match_score": 90,
        "completion": True,
        "schedule_status": "ontime",
        "beyond_requirements": ["自定义主题切换", "集成 CI"],
        "bonus": 5,
        "comment": "整个项目周期坚持得很好，整体实现符合要求，还自主增加了超出设计的主题切换功能，值得表扬！",
        "reasoning": "综合全部任务与当前代码评估",
    }


@pytest.fixture
def snap():
    return {"files": [{"path": "main.py", "content": "print(1)", "truncated": False}]}


class TestFullModeHappyPath:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.repo_total_loc")
    @patch("app.services.pipeline.extract_snapshot")
    def test_full_creates_one_assessment_per_student_and_skips_sync(
            self, mock_snap, mock_loc, mock_sync_day, mock_score, mock_send,
            session, seed_full, mock_settings, full_ai_response):
        from app.services.pipeline import run_today
        mock_snap.return_value = {"files": []}
        mock_loc.return_value = 500
        mock_score.return_value = full_ai_response
        mock_send.return_value = None

        result = run_today(seed_full['target'], session=session, eval_mode='full')

        mock_sync_day.assert_not_called()
        assert result['success'] == 2
        assert result['failed'] == 0

        rows = session.exec(select(Assessment)).all()
        assert len(rows) == 2
        for a in rows:
            assert a.eval_type == 'full'
            assert a.date == seed_full['target']
            assert a.status == 'done'
            assert a.volume_score is None or a.total_score > 0

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.repo_total_loc")
    @patch("app.services.pipeline.extract_snapshot")
    def test_full_aggregates_applicable_plans_only(
            self, mock_snap, mock_loc, mock_sync_day, mock_score, mock_send,
            session, seed_full, mock_settings, full_ai_response, snap):
        from app.services.pipeline import run_today
        mock_snap.return_value = snap
        mock_loc.return_value = 500
        mock_send.return_value = None

        seen = {}

        def capture(context, settings):
            seen[context['student_id']] = context
            return full_ai_response

        mock_score.side_effect = capture

        run_today(seed_full['target'], session=session, eval_mode='full')

        assert set(seen.keys()) == {seed_full['s1'].id, seed_full['s2'].id}

        ctx_s1 = seen[seed_full['s1'].id]
        assert ctx_s1['eval_mode'] == 'full'
        # 聚合张三的所有适用计划：全体计划 × 2 天 + 张三专属；排除未来日期与他生专属
        assert '第一天：搭建项目骨架' in ctx_s1['plan_content']
        assert '第二天：完成登录模块' in ctx_s1['plan_content']
        assert '登录模块（张三专属）' in ctx_s1['plan_content']
        assert '未来' not in ctx_s1['plan_content']
        assert '李四专属' not in ctx_s1['plan_content']
        assert ctx_s1['commits'] == []
        assert ctx_s1['loc_additions'] == 500
        assert ctx_s1['project_files'][0]['path'] == 'main.py'

        ctx_s2 = seen[seed_full['s2'].id]
        assert '第二天：完成登录模块' in ctx_s2['plan_content']
        assert '李四专属任务' in ctx_s2['plan_content']
        assert '张三专属' not in ctx_s2['plan_content']
        assert '未来' not in ctx_s2['plan_content']

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.repo_total_loc")
    @patch("app.services.pipeline.extract_snapshot")
    def test_full_skips_student_without_plans(
            self, mock_snap, mock_loc, mock_sync_day, mock_score, mock_send,
            session, seed_full, mock_settings, full_ai_response):
        """有项目但没有任何历史计划的学生不应被评测。"""
        from app.services.pipeline import run_today
        mock_snap.return_value = {"files": []}
        mock_loc.return_value = 500
        mock_score.return_value = full_ai_response
        mock_send.return_value = None

        # 再添加一个没有计划覆盖的学生（其项目无任何计划，含全体计划）
        p2 = Project(name='无计划项目')
        session.add(p2)
        session.commit()
        session.refresh(p2)
        s4 = Student(name='丁六', email='dl@x.com', github_repo='dl/noplan',
                     project_id=p2.id)
        session.add(s4)
        session.commit()

        result = run_today(seed_full['target'], session=session, eval_mode='full')

        assert result['success'] == 2
        scored_ids = {c.args[0]['student_id'] for c in mock_score.call_args_list}
        assert s4.id not in scored_ids


class TestFullModeBonus:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.repo_total_loc")
    @patch("app.services.pipeline.extract_snapshot")
    def test_bonus_added_to_total_and_persisted(
            self, mock_snap, mock_loc, mock_sync_day, mock_score, mock_send,
            session, seed_full, mock_settings, full_ai_response):
        from app.services.pipeline import run_today
        mock_snap.return_value = {"files": []}
        mock_loc.return_value = 500
        mock_score.return_value = full_ai_response
        mock_send.return_value = None

        run_today(seed_full['target'], session=session, eval_mode='full')

        config = session.exec(select(ScoringConfig)).first()
        base = compute_final({
            "loc": 500, "volume": None, "quality": 85, "match": 90,
            "schedule_status": "ontime",
        }, config)
        with_bonus = compute_final({
            "loc": 500, "volume": None, "quality": 85, "match": 90,
            "schedule_status": "ontime", "bonus": 5,
        }, config)
        assert with_bonus - base == pytest.approx(5.0)

        a = session.exec(select(Assessment)).first()
        assert a.total_score == pytest.approx(with_bonus, abs=0.01)
        assert a.bonus_score == 5


class TestFullModeIdempotency:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.repo_total_loc")
    @patch("app.services.pipeline.extract_snapshot")
    def test_repeated_run_does_not_duplicate(
            self, mock_snap, mock_loc, mock_sync_day, mock_score, mock_send,
            session, seed_full, mock_settings, full_ai_response):
        from app.services.pipeline import run_today
        mock_snap.return_value = {"files": []}
        mock_loc.return_value = 500
        mock_score.return_value = full_ai_response
        mock_send.return_value = None

        run_today(seed_full['target'], session=session, eval_mode='full')
        run_today(seed_full['target'], session=session, eval_mode='full')

        rows = session.exec(select(Assessment)).all()
        assert len(rows) == 2
        assert all(a.eval_type == 'full' for a in rows)


class TestFullModeOnlyMissing:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.repo_total_loc")
    @patch("app.services.pipeline.extract_snapshot")
    def test_only_missing_skips_done_full(
            self, mock_snap, mock_loc, mock_sync_day, mock_score, mock_send,
            session, seed_full, mock_settings, full_ai_response):
        """已 done 的 full 评测在 only_missing 下被跳过。"""
        from app.services.pipeline import run_today
        mock_snap.return_value = {"files": []}
        mock_loc.return_value = 500
        mock_score.return_value = full_ai_response
        mock_send.return_value = None

        session.add(Assessment(
            student_id=seed_full['s1'].id,
            project_id=seed_full['p1'].id,
            date=seed_full['target'],
            eval_type='full',
            status='done',
            total_score=91,
        ))
        session.commit()

        result = run_today(seed_full['target'], session=session, eval_mode='full', only_missing=True)

        assert mock_score.call_count == 1
        assert result['success'] == 1
        assert result['skipped_existing'] == 1

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.repo_total_loc")
    @patch("app.services.pipeline.extract_snapshot")
    def test_only_missing_not_blocked_by_diff_done(
            self, mock_snap, mock_loc, mock_sync_day, mock_score, mock_send,
            session, seed_full, mock_settings, full_ai_response):
        """同日期的 diff（daily）done 评测不应阻塞 full 评测。"""
        from app.services.pipeline import run_today
        mock_snap.return_value = {"files": []}
        mock_loc.return_value = 500
        mock_score.return_value = full_ai_response
        mock_send.return_value = None

        session.add(Assessment(
            student_id=seed_full['s1'].id,
            project_id=seed_full['p1'].id,
            date=seed_full['target'],
            eval_type='diff',
            status='done',
            total_score=60,
        ))
        session.commit()

        result = run_today(seed_full['target'], session=session, eval_mode='full', only_missing=True)

        assert mock_score.call_count == 2
        assert result['success'] == 2


class TestFullModeProjectScoped:

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.repo_total_loc")
    @patch("app.services.pipeline.extract_snapshot")
    def test_project_id_scopes_full_eval(
            self, mock_snap, mock_loc, mock_sync_day, mock_score, mock_send,
            session, mock_settings, full_ai_response):
        from app.services.pipeline import run_today
        target = date(2026, 8, 21)
        p1 = Project(name='项目一'); p2 = Project(name='项目二')
        session.add_all([p1, p2]); session.commit(); session.refresh(p1); session.refresh(p2)

        sa = Student(name='甲', email='a@x.com', github_repo='a/r', project_id=p1.id)
        sb = Student(name='乙', email='b@x.com', github_repo='b/r', project_id=p2.id)
        session.add_all([sa, sb]); session.commit()
        for s_ in [sa, sb]:
            session.refresh(s_)
        session.add(DailyPlan(project_id=p1.id, date=target, content='任务一', student_id=None))
        session.add(DailyPlan(project_id=p2.id, date=target, content='任务二', student_id=None))
        session.add(ScoringConfig())
        session.commit()

        mock_snap.return_value = {"files": []}
        mock_loc.return_value = 100
        mock_score.return_value = full_ai_response
        mock_send.return_value = None

        result = run_today(target, session=session, eval_mode='full', project_id=p1.id)

        assert result['success'] == 1
        pairs = {(a.student_id, a.project_id) for a in session.exec(select(Assessment)).all()}
        assert pairs == {(sa.id, p1.id)}


class TestAssessmentMigration:

    def test_migration_rebuilds_assessment_table(self):
        from sqlalchemy import create_engine, inspect, text
        from app.database import _migrate_sqlite_engine

        eng = create_engine("sqlite:///:memory:")
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE assessment (
                    id INTEGER PRIMARY KEY,
                    student_id INTEGER NOT NULL,
                    project_id INTEGER NOT NULL,
                    date DATE NOT NULL,
                    quality_score FLOAT,
                    match_score FLOAT,
                    volume_score FLOAT,
                    schedule_status VARCHAR DEFAULT 'ontime',
                    schedule_adjustment FLOAT DEFAULT 0.0,
                    total_score FLOAT,
                    comment VARCHAR,
                    status VARCHAR DEFAULT 'pending',
                    attempts INTEGER DEFAULT 0,
                    next_retry_at DATETIME,
                    saved_context_json VARCHAR,
                    email_sent BOOLEAN DEFAULT 0,
                    created_at DATETIME,
                    evaluated_at DATETIME,
                    UNIQUE (student_id, project_id, date)
                )
            """))
            conn.execute(text(
                "INSERT INTO assessment (student_id, project_id, date, status, total_score) "
                "VALUES (1, 1, '2026-08-21', 'done', 88)"
            ))

        _migrate_sqlite_engine(eng)

        cols = {c['name'] for c in inspect(eng).get_columns('assessment')}
        assert 'eval_type' in cols
        assert 'bonus_score' in cols

        with Session(eng) as s:
            rows = s.exec(select(Assessment)).all()
            assert len(rows) == 1
            assert rows[0].eval_type == 'diff'  # 旧数据默认视为 diff
            assert rows[0].total_score == 88

            # diff + full 同日期可并存
            s.add(Assessment(student_id=1, project_id=1, date=date(2026, 8, 21), eval_type='full'))
            s.commit()
            # diff 重复仍被唯一约束拒绝
            with pytest.raises(Exception):
                s.add(Assessment(student_id=1, project_id=1, date=date(2026, 8, 21), eval_type='diff'))
                s.commit()


class TestFullModeCodeExtractionFailure:
    """代码提取失败不得伪装成「学生没写代码」的 0 分 done（生产事故回归锁定）。"""

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.repo_total_loc")
    @patch("app.services.pipeline.extract_snapshot")
    def test_snapshot_failure_marks_failed_not_zero_score(
            self, mock_snap, mock_loc, mock_sync_day, mock_score, mock_send,
            session, seed_full, mock_settings, full_ai_response):
        from app.services.pipeline import run_today
        mock_snap.side_effect = RuntimeError("镜像更新超时")
        mock_loc.return_value = 3390
        mock_score.return_value = full_ai_response
        mock_send.return_value = None

        result = run_today(seed_full['target'], session=session, eval_mode='full')

        mock_score.assert_not_called()
        assert result['success'] == 0
        assert result['failed'] == 2

        rows = session.exec(select(Assessment)).all()
        assert len(rows) == 2
        for a in rows:
            assert a.status == 'failed'
            assert a.total_score is None
            assert a.saved_context_json is not None
            assert a.next_retry_at is not None

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.repo_total_loc")
    @patch("app.services.pipeline.extract_snapshot")
    def test_total_loc_failure_marks_failed(
            self, mock_snap, mock_loc, mock_sync_day, mock_score, mock_send,
            session, seed_full, mock_settings, full_ai_response, snap):
        from app.services.pipeline import run_today
        mock_snap.return_value = snap
        mock_loc.side_effect = RuntimeError("镜像更新超时")
        mock_score.return_value = full_ai_response
        mock_send.return_value = None

        result = run_today(seed_full['target'], session=session, eval_mode='full')

        mock_score.assert_not_called()
        assert result['failed'] == 2
        assert all(a.status == 'failed' for a in session.exec(select(Assessment)).all())

    @patch("app.services.pipeline.send_daily_comments")
    @patch("app.services.pipeline.score_student")
    @patch("app.services.pipeline.sync_day")
    @patch("app.services.pipeline.repo_total_loc")
    @patch("app.services.pipeline.extract_snapshot")
    def test_genuinely_empty_repo_still_scored(
            self, mock_snap, mock_loc, mock_sync_day, mock_score, mock_send,
            session, seed_full, mock_settings, full_ai_response):
        """提取成功但仓库确实为空 → 正常评测（真 0 代码，与提取失败区分）。"""
        from app.services.pipeline import run_today
        mock_snap.return_value = {"files": [], "total_files_in_repo": 0}
        mock_loc.return_value = 0
        mock_score.return_value = full_ai_response
        mock_send.return_value = None

        result = run_today(seed_full['target'], session=session, eval_mode='full')

        assert result['success'] == 2
        assert mock_score.call_count == 2


class TestFullAiScoringValidation:

    def test_full_validation_requires_beyond_and_bonus(self):
        from app.services.ai_scoring_service import _validate_response, LLMInvalidResponse, REQUIRED_FIELDS

        base = {
            "quality_score": 85, "match_score": 90, "completion": True,
            "schedule_status": "ontime", "comment": "很好，表现优秀", "reasoning": "依据",
            "beyond_requirements": ["自定义功能"], "bonus": 5,
        }
        # diff 模式只需基础字段
        _validate_response({k: v for k, v in base.items() if k in REQUIRED_FIELDS})
        # full 模式缺 bonus
        missing_bonus = {**base}
        missing_bonus.pop('bonus')
        with pytest.raises(LLMInvalidResponse):
            _validate_response(missing_bonus, is_full=True)
        # full 模式缺 beyond_requirements
        missing_beyond = {**base}
        missing_beyond.pop('beyond_requirements')
        with pytest.raises(LLMInvalidResponse):
            _validate_response(missing_beyond, is_full=True)
        # bonus 越界
        with pytest.raises(LLMInvalidResponse):
            _validate_response({**base, "bonus": 16}, is_full=True)
        with pytest.raises(LLMInvalidResponse):
            _validate_response({**base, "bonus": -1}, is_full=True)
        # beyond_requirements 类型错误
        with pytest.raises(LLMInvalidResponse):
            _validate_response({**base, "beyond_requirements": "not-a-list"}, is_full=True)
        # 合法 full 响应通过
        assert _validate_response(base, is_full=True)['bonus'] == 5

    def test_score_student_full_uses_full_prompt_and_validates(self, mock_settings):
        from app.services import ai_scoring_service as svc

        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured['kwargs'] = kwargs
                return _resp(json.dumps({
                    "quality_score": 85, "match_score": 90, "completion": True,
                    "schedule_status": "ontime",
                    "beyond_requirements": ["自定义功能"], "bonus": 5,
                    "comment": "很好，表现优秀", "reasoning": "依据",
                }, ensure_ascii=False))

        class FakeClient:
            def __init__(self, *a, **kw):
                self.chat = _Chat(_chat)

        class _Chat:
            def __init__(self, completions):
                self.completions = completions

        class _Resp:
            def __init__(self, content):
                self.choices = [_Choice(content)]

        class _Choice:
            def __init__(self, content):
                self.message = _Msg(content)

        class _Msg:
            def __init__(self, content):
                self.content = content

        def _resp(content):
            return _Resp(content)

        _chat = FakeCompletions()

        with patch.object(svc, 'OpenAI', FakeClient):
            result = svc.score_student(
                {"eval_mode": "full", "plan_content": "任务", "commits": [],
                 "loc_additions": 500, "loc_deletions": 0, "student_id": 1},
                mock_settings,
            )

        system_prompt = captured['kwargs']['messages'][0]['content']
        assert '综合评测' in system_prompt
        assert 'beyond_requirements' in system_prompt
        user_msg = captured['kwargs']['messages'][1]['content']
        assert '阶段综合任务' in user_msg
        assert result['bonus'] == 5
        assert result['beyond_requirements'] == ["自定义功能"]

    def test_score_student_full_rejects_invalid_bonus(self, mock_settings):
        from app.services import ai_scoring_service as svc
        from app.services.ai_scoring_service import LLMInvalidResponse

        class FakeCompletions:
            def create(self, **kwargs):
                return _resp(json.dumps({
                    "quality_score": 85, "match_score": 90, "completion": True,
                    "schedule_status": "ontime",
                    "beyond_requirements": [], "bonus": 99,
                    "comment": "很好，表现优秀", "reasoning": "依据",
                }, ensure_ascii=False))

        class FakeClient:
            def __init__(self, *a, **kw):
                self.chat = _Chat(FakeCompletions())

        class _Chat:
            def __init__(self, completions):
                self.completions = completions

        class _Resp:
            def __init__(self, content):
                self.choices = [_Choice(content)]

        class _Choice:
            def __init__(self, content):
                self.message = _Msg(content)

        class _Msg:
            def __init__(self, content):
                self.content = content

        def _resp(content):
            return _Resp(content)

        with patch.object(svc, 'OpenAI', FakeClient):
            with pytest.raises(LLMInvalidResponse):
                svc.score_student(
                    {"eval_mode": "full", "plan_content": "任务", "commits": [],
                     "loc_additions": 100, "loc_deletions": 0, "student_id": 1},
                    mock_settings,
                )