import os
import sys
from datetime import date

import pytest
from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.models import Assessment, GithubActivity, Project, ScoringConfig, Student
from app.services.scoring_engine import compute_final
from scripts.backfill_scores import backfill


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def config(session):
    cfg = ScoringConfig(w_volume=0.4, w_quality=0.3, w_match=0.3,
                        loc_threshold=200, schedule_bonus=2.0,
                        schedule_penalty=-3.0)
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    return cfg


@pytest.fixture
def ctx(session):
    st = Student(name='张三', email='z@e.com', github_repo='z/r')
    pj = Project(name='项目A')
    session.add_all([st, pj])
    session.commit()
    session.refresh(st)
    session.refresh(pj)
    return st, pj


def _make(session, st, pj, **kw):
    a = Assessment(student_id=st.id, project_id=pj.id,
                   date=kw.pop('date', date(2026, 8, 21)),
                   status=kw.pop('status', 'done'), **kw)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


class TestVolumeReversedFromTotal:

    def test_reverses_exact_volume_for_uncapped_row(self, session, config, ctx):
        st, pj = ctx
        # 正向算一次 total，清掉 volume_score，验证能原值还原
        engine_input = {'loc': 120, 'volume': None, 'quality': 70.0,
                        'match': 60.0, 'schedule_status': 'behind', 'bonus': 0}
        total = compute_final(engine_input, config)
        a = _make(session, st, pj, quality_score=70.0, match_score=60.0,
                  bonus_score=0.0, schedule_status='behind',
                  schedule_adjustment=-3.0, total_score=total,
                  volume_score=None, eval_type='diff')
        session.add(GithubActivity(student_id=st.id, date=a.date,
                                   loc_additions=120, loc_deletions=0))
        session.commit()

        report = backfill(session)
        session.refresh(a)
        assert report.volume_reversed == 1
        assert report.volume_from_loc == 0
        assert a.volume_score == pytest.approx(60.0, abs=0.01)

    def test_reversal_accounts_for_bonus_and_adjustment(self, session, config, ctx):
        st, pj = ctx
        engine_input = {'loc': 300, 'volume': None, 'quality': 80.0,
                        'match': 50.0, 'schedule_status': 'ahead', 'bonus': 4.0}
        total = compute_final(engine_input, config)
        assert total < 100.0
        a = _make(session, st, pj, quality_score=80.0, match_score=50.0,
                  bonus_score=4.0, schedule_status='ahead',
                  schedule_adjustment=2.0, total_score=total,
                  volume_score=None, eval_type='diff')
        backfill(session)
        session.refresh(a)
        assert a.volume_score == pytest.approx(100.0, abs=0.01)


class TestCappedRowsFallBackToLoc:

    def test_capped_diff_row_uses_loc_threshold(self, session, config, ctx):
        st, pj = ctx
        a = _make(session, st, pj, quality_score=95.0, match_score=95.0,
                  bonus_score=10.0, schedule_status='ontime',
                  total_score=100.0, volume_score=None, eval_type='diff')
        session.add(GithubActivity(student_id=st.id, date=a.date,
                                   loc_additions=50, loc_deletions=10))
        session.commit()

        report = backfill(session)
        session.refresh(a)
        assert report.volume_from_loc == 1
        assert report.volume_reversed == 0
        assert a.volume_score == pytest.approx(30.0, abs=0.01)

    def test_capped_full_row_gets_hundred(self, session, config, ctx):
        st, pj = ctx
        a = _make(session, st, pj, quality_score=82.0, match_score=85.0,
                  bonus_score=10.0, schedule_status='ontime',
                  total_score=100.0, volume_score=None, eval_type='full')
        report = backfill(session)
        session.refresh(a)
        assert report.volume_from_loc == 1
        assert a.volume_score == 100.0

    def test_capped_diff_row_without_activity_is_unresolved(self, session, config, ctx):
        st, pj = ctx
        a = _make(session, st, pj, quality_score=99.0, match_score=99.0,
                  bonus_score=12.0, schedule_status='ahead',
                  total_score=100.0, volume_score=None, eval_type='diff')
        report = backfill(session)
        session.refresh(a)
        assert report.volume_unresolved == [a.id]
        assert a.volume_score is None


class TestScheduleAdjustmentRepair:

    @pytest.mark.parametrize("status,expected", [
        ('ahead', 2.0), ('behind', -3.0), ('ontime', 0.0),
    ])
    def test_adjustment_derived_from_status(self, session, config, ctx,
                                            status, expected):
        st, pj = ctx
        a = _make(session, st, pj, quality_score=70.0, match_score=70.0,
                  schedule_status=status, schedule_adjustment=0.0,
                  total_score=70.0, volume_score=70.0)
        backfill(session)
        session.refresh(a)
        assert a.schedule_adjustment == expected

    def test_correct_adjustment_not_counted_as_fixed(self, session, config, ctx):
        st, pj = ctx
        _make(session, st, pj, quality_score=70.0, match_score=70.0,
              schedule_status='behind', schedule_adjustment=-3.0,
              total_score=70.0, volume_score=70.0)
        report = backfill(session)
        assert report.adjustment_fixed == 0


class TestIdempotencyAndSafety:

    def test_existing_volume_score_never_overwritten(self, session, config, ctx):
        st, pj = ctx
        a = _make(session, st, pj, quality_score=70.0, match_score=60.0,
                  schedule_status='ontime', schedule_adjustment=0.0,
                  total_score=64.0, volume_score=12.34, eval_type='diff')
        backfill(session)
        session.refresh(a)
        assert a.volume_score == 12.34

    def test_second_run_is_noop(self, session, config, ctx):
        st, pj = ctx
        _make(session, st, pj, quality_score=70.0, match_score=60.0,
              bonus_score=0.0, schedule_status='behind',
              schedule_adjustment=0.0, total_score=61.0,
              volume_score=None, eval_type='full')
        first = backfill(session)
        assert first.volume_total == 1
        assert first.adjustment_fixed == 1
        second = backfill(session)
        assert second.volume_total == 0
        assert second.adjustment_fixed == 0

    def test_non_done_rows_are_skipped(self, session, config, ctx):
        st, pj = ctx
        a = _make(session, st, pj, status='failed', schedule_status='behind',
                  schedule_adjustment=0.0, volume_score=None)
        report = backfill(session)
        session.refresh(a)
        assert report.skipped_not_done == 1
        assert a.volume_score is None
        assert a.schedule_adjustment == 0.0

    def test_dry_run_does_not_persist(self, session, config, ctx):
        st, pj = ctx
        a = _make(session, st, pj, quality_score=70.0, match_score=60.0,
                  bonus_score=0.0, schedule_status='behind',
                  schedule_adjustment=0.0, total_score=61.0,
                  volume_score=None, eval_type='full')
        aid = a.id
        report = backfill(session, dry_run=True)
        assert report.volume_total == 1
        session.expire_all()
        reloaded = session.get(Assessment, aid)
        assert reloaded.volume_score is None
        assert reloaded.schedule_adjustment == 0.0

    def test_total_score_is_never_modified(self, session, config, ctx):
        st, pj = ctx
        a = _make(session, st, pj, quality_score=70.0, match_score=60.0,
                  bonus_score=0.0, schedule_status='behind',
                  schedule_adjustment=0.0, total_score=61.0,
                  volume_score=None, eval_type='full')
        backfill(session)
        session.refresh(a)
        assert a.total_score == 61.0
