from sqlmodel import Session, select
from app.models import ScoringConfig
from app.database import get_session


def seed_config(session: Session = None) -> None:
    if session is None:
        with next(get_session()) as s:
            session = s
            should_close = True
    else:
        should_close = False

    try:
        existing = session.exec(select(ScoringConfig)).first()
        if existing:
            return
        config = ScoringConfig(
            w_volume=1 / 3,
            w_quality=1 / 3,
            w_match=1 / 3,
            loc_threshold=100,
            schedule_bonus=5.0,
            schedule_penalty=-5.0,
        )
        session.add(config)
        session.commit()
        session.refresh(config)
    finally:
        if should_close:
            session.close()
