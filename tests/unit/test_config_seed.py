import sys
import os
import pytest
from sqlmodel import SQLModel, create_engine, Session, select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.models import ScoringConfig


@pytest.fixture
def engine():
    return create_engine("sqlite:///:memory:")


@pytest.fixture
def session(engine):
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class TestSeedConfig:

    def test_seed_creates_default_config(self, session, engine):
        from app.services.config_seed import seed_config
        seed_config(session=session)
        config = session.exec(select(ScoringConfig)).first()
        assert config is not None
        assert config.w_volume == pytest.approx(1 / 3)
        assert config.w_quality == pytest.approx(1 / 3)
        assert config.w_match == pytest.approx(1 / 3)
        assert config.loc_threshold == 100
        assert config.schedule_bonus == 5.0
        assert config.schedule_penalty == -5.0

    def test_seed_idempotent_no_duplicate(self, session, engine):
        from app.services.config_seed import seed_config
        seed_config(session=session)
        seed_config(session=session)
        count = session.exec(select(ScoringConfig)).all()
        assert len(count) == 1

    def test_seed_skips_when_already_exists(self, session, engine):
        from app.services.config_seed import seed_config
        existing = ScoringConfig(w_volume=0.9, w_quality=0.5)
        session.add(existing)
        session.commit()
        seed_config(session=session)
        config = session.exec(select(ScoringConfig)).first()
        assert config.w_volume == 0.9
        assert config.w_quality == 0.5
