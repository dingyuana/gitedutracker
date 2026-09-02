"""回填历史 Assessment 的 volume_score / schedule_adjustment。

背景：`pipeline` 的两处主评分路径与 `retry_service` 曾漏写 `volume_score`
和 `schedule_adjustment` 两个字段（见 fix 提交）。这些字段的值当时已经
参与了 `total_score` 的计算，只是没有落库，因此可以无损还原，无需重新
调用 LLM。

还原方式
--------
1. `schedule_adjustment` 由 `schedule_status` 直接决定，查配置即可，无歧义。

2. `volume_score` 从 `total_score` 代数反解：

       total = min(100, w_v*vol + w_q*quality + w_m*match + adjustment + bonus)

   未触及 100 上限时可精确反解 vol。已被 `min(100, ...)` 截断的行无法反解，
   退化为按 `loc_threshold` 重新推导（与 `derive_volume_score` 同一公式）：
   `diff` 模式用当日 GithubActivity 的增删行数，`full` 模式因整仓 LOC 恒
   远超阈值而取满分 100。

用法
----
    .venv/bin/python -m scripts.backfill_scores --dry-run   # 只报告，不写库
    .venv/bin/python -m scripts.backfill_scores             # 实际写入
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, select

from app.models import Assessment, GithubActivity, ScoringConfig
from app.services.scoring_engine import derive_schedule_adjustment

# 反解容差：total_score 落库时 round(2)，反解误差被权重放大后仍应远小于此
_CAP = 100.0
_EPS = 1e-6


@dataclass
class BackfillReport:
    volume_reversed: int = 0
    volume_from_loc: int = 0
    volume_unresolved: list[int] = field(default_factory=list)
    adjustment_fixed: int = 0
    skipped_not_done: int = 0

    @property
    def volume_total(self) -> int:
        return self.volume_reversed + self.volume_from_loc


def _normalised_weights(config: ScoringConfig) -> tuple[float, float, float]:
    w_sum = config.w_volume + config.w_quality + config.w_match
    if w_sum <= 0:
        third = 1.0 / 3
        return third, third, third
    return (config.w_volume / w_sum, config.w_quality / w_sum,
            config.w_match / w_sum)


def _reverse_volume(a: Assessment, config: ScoringConfig) -> Optional[float]:
    """从 total_score 代数反解 volume_score；被 100 截断时返回 None。"""
    if a.total_score is None or a.total_score >= _CAP - _EPS:
        return None
    w_volume, w_quality, w_match = _normalised_weights(config)
    if w_volume <= 0:
        return None

    adjustment = derive_schedule_adjustment(
        {'schedule_status': a.schedule_status}, config)
    base = (a.total_score - adjustment - (a.bonus_score or 0.0)
            - w_quality * (a.quality_score or 0.0)
            - w_match * (a.match_score or 0.0))
    volume = base / w_volume
    if not (-0.5 <= volume <= 100.5):
        return None
    return round(min(max(volume, 0.0), 100.0), 2)


def _volume_from_loc(a: Assessment, config: ScoringConfig,
                     loc: Optional[int]) -> Optional[float]:
    """按 loc_threshold 推导，与 derive_volume_score 的 fallback 同公式。

    `full` 模式统计整仓 LOC，恒远超阈值，取满分。
    """
    if config.loc_threshold <= 0:
        return None
    if a.eval_type == 'full':
        return 100.0
    if loc is None:
        return None
    return round(min(100.0, loc / config.loc_threshold * 100), 2)


def backfill(session: Session, dry_run: bool = False) -> BackfillReport:
    config = session.exec(select(ScoringConfig)).first() or ScoringConfig()
    report = BackfillReport()

    loc_by_key: dict[tuple[int, object], int] = {
        (g.student_id, g.date): (g.loc_additions or 0) + (g.loc_deletions or 0)
        for g in session.exec(select(GithubActivity)).all()
    }

    for a in session.exec(select(Assessment)).all():
        if a.status != 'done':
            report.skipped_not_done += 1
            continue

        expected_adjustment = derive_schedule_adjustment(
            {'schedule_status': a.schedule_status}, config)
        if (a.schedule_adjustment or 0.0) != expected_adjustment:
            a.schedule_adjustment = expected_adjustment
            report.adjustment_fixed += 1

        if a.volume_score is None:
            volume = _reverse_volume(a, config)
            if volume is not None:
                report.volume_reversed += 1
            else:
                volume = _volume_from_loc(
                    a, config, loc_by_key.get((a.student_id, a.date)))
                if volume is not None:
                    report.volume_from_loc += 1
            if volume is None:
                report.volume_unresolved.append(a.id)
            else:
                a.volume_score = volume

        if not dry_run:
            session.add(a)

    if dry_run:
        session.rollback()
    else:
        session.commit()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true',
                        help='只报告将要写入的内容，不提交事务')
    args = parser.parse_args()

    from app.database import engine

    with Session(engine) as session:
        report = backfill(session, dry_run=args.dry_run)

    mode = '[dry-run] ' if args.dry_run else ''
    print(f"{mode}volume_score 回填 {report.volume_total} 条"
          f"（代数反解 {report.volume_reversed}，loc 推导 {report.volume_from_loc}）")
    print(f"{mode}schedule_adjustment 修正 {report.adjustment_fixed} 条")
    print(f"{mode}跳过非 done 状态 {report.skipped_not_done} 条")
    if report.volume_unresolved:
        print(f"{mode}无法还原 {len(report.volume_unresolved)} 条: "
              f"{report.volume_unresolved}")


if __name__ == '__main__':
    main()
