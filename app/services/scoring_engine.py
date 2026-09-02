from __future__ import annotations

from typing import Any

from app.models import ScoringConfig


def derive_volume_score(subscores: dict[str, Any], config: ScoringConfig) -> float:
    loc = subscores.get('loc', 0)
    fallback = min(100, loc / config.loc_threshold * 100) if config.loc_threshold > 0 else 0
    explicit = subscores.get('volume')
    return round(float(explicit if explicit is not None else fallback), 2)


def derive_schedule_adjustment(subscores: dict[str, Any], config: ScoringConfig) -> float:
    status = subscores.get('schedule_status', 'ontime')
    if status == 'ahead':
        return float(config.schedule_bonus)
    if status == 'behind':
        return float(config.schedule_penalty)
    return 0.0


def compute_final(subscores: dict[str, Any], config: ScoringConfig) -> float:
    w_sum = config.w_volume + config.w_quality + config.w_match
    if w_sum <= 0:
        w_volume, w_quality, w_match = 1.0 / 3, 1.0 / 3, 1.0 / 3
    else:
        w_volume, w_quality, w_match = (
            config.w_volume / w_sum,
            config.w_quality / w_sum,
            config.w_match / w_sum,
        )

    vol = derive_volume_score(subscores, config)
    base_score = (
        w_volume * vol +
        w_quality * subscores.get('quality', 0) +
        w_match * subscores.get('match', 0)
    )

    adjustment = derive_schedule_adjustment(subscores, config)
    bonus = subscores.get('bonus', 0) or 0
    return min(100.0, round(base_score + adjustment + bonus, 2))
