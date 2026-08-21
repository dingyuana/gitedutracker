import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from app.models import ScoringConfig
from app.services.scoring_engine import compute_final


def _config(**kwargs):
    defaults = dict(
        w_volume=0.333,
        w_quality=0.333,
        w_match=0.333,
        loc_threshold=100,
        schedule_bonus=5.0,
        schedule_penalty=-5.0,
    )
    defaults.update(kwargs)
    return ScoringConfig(**defaults)


def _subscores(**kwargs):
    defaults = dict(volume=80, quality=80, match=80, schedule_status='ontime', loc=80)
    defaults.update(kwargs)
    return defaults


class TestComputeFinal:

    def test_equal_weights_equal_subscores_returns_same_score(self):
        config = _config()
        subscores = _subscores(volume=80, quality=80, match=80, schedule_status='ontime')
        result = compute_final(subscores, config)
        assert result == 80.0

    def test_behind_schedule_reduces_score(self):
        config = _config(schedule_bonus=5.0, schedule_penalty=-5.0)
        subscores = _subscores(volume=80, quality=80, match=80, schedule_status='behind')
        result = compute_final(subscores, config)
        assert result == 75.0

    def test_ahead_schedule_increases_score(self):
        config = _config(schedule_bonus=5.0, schedule_penalty=-5.0)
        subscores = _subscores(volume=80, quality=80, match=80, schedule_status='ahead')
        result = compute_final(subscores, config)
        assert result == 85.0

    def test_missing_weights_fallback_to_equal(self):
        config = _config(w_volume=0.0, w_quality=0.0, w_match=0.0)
        subscores = _subscores(volume=70, quality=70, match=70, schedule_status='ontime')
        result = compute_final(subscores, config)
        assert result == 70.0

    def test_loc_normalization_below_threshold(self):
        config = _config(loc_threshold=100)
        subscores = _subscores(volume=None, quality=100, match=100, loc=50, schedule_status='ontime')
        result = compute_final(subscores, config)
        expected = (50 / 100 * 100) * (1 / 3) + 100 * (1 / 3) + 100 * (1 / 3)
        assert result == round(expected, 2)

    def test_loc_above_threshold_caps_at_100(self):
        config = _config(loc_threshold=100)
        subscores = _subscores(volume=None, quality=0, match=0, loc=200, schedule_status='ontime')
        result = compute_final(subscores, config)
        volume = min(100, 200 / 100 * 100)
        expected = volume * (1 / 3)
        assert result == round(expected, 2)
