"""
points_engine.py
────────────────
Stateless points calculation engine for the Recognition Service.

All multiplier values are now resolved from the database by the service layer
and passed in as plain floats.  The engine itself has zero DB / IO dependencies
and remains trivially unit-testable.

Formula
-------
    raw_points       = rating × category_multiplier × reviewer_weight × seasonal_multiplier
    effective_points = raw_points × decay_rate ^ quarters_since_award

What moved to the DB (3NF fixes)
---------------------------------
| Was hardcoded here             | Now lives in table          |
|--------------------------------|-----------------------------|
| CATEGORY_MULTIPLIERS dict      | review_categories.multiplier|
| ROLE_WEIGHTS dict              | roles.reviewer_weight       |
| _seasonal_multiplier() if/elif | seasonal_multipliers table  |
| DECAY_RATE = 0.9 constant      | points_config (DECAY_RATE)  |
"""

from __future__ import annotations

import math
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────
# 1.  TIME HELPERS
# ──────────────────────────────────────────────────────────────

def quarters_elapsed(award_dt: datetime, reference_dt: datetime | None = None) -> int:
    """
    Integer number of complete quarters between award_dt and reference_dt
    (defaults to now).  Never negative.
    """
    if reference_dt is None:
        reference_dt = datetime.now(timezone.utc)

    # Normalise both to UTC-aware
    if award_dt.tzinfo is None:
        award_dt = award_dt.replace(tzinfo=timezone.utc)
    if reference_dt.tzinfo is None:
        reference_dt = reference_dt.replace(tzinfo=timezone.utc)

    delta_months = (
        (reference_dt.year  - award_dt.year)  * 12
        + (reference_dt.month - award_dt.month)
    )
    return max(0, delta_months // 3)


def apply_decay(raw_points: float, quarters: int, decay_rate: float = 0.9) -> float:
    """
    effective_points = raw_points × decay_rate ^ quarters

    decay_rate is passed in (resolved from points_config table) so the
    constant is no longer baked into the engine.
    """
    return raw_points * math.pow(decay_rate, quarters)


# ──────────────────────────────────────────────────────────────
# 2.  RESULT CONTAINER
# ──────────────────────────────────────────────────────────────

class PointsResult:
    """
    Carries every intermediate value so callers can log / store all steps.

    category_code is a human-readable label (e.g. "INNOVATION") for logging;
    it is not used in any calculation.
    """

    __slots__ = (
        "rating",
        "category_code",
        "category_multiplier",
        "reviewer_weight",
        "seasonal_multiplier",
        "decay_rate",
        "raw_points",
        "quarters_elapsed",
        "effective_points",
    )

    def __init__(
        self,
        rating: int,
        category_code: str,
        category_multiplier: float,
        reviewer_weight: float,
        seasonal_multiplier: float,
        decay_rate: float,
        raw_points: float,
        quarters_elapsed: int,
        effective_points: float,
    ) -> None:
        self.rating              = rating
        self.category_code       = category_code
        self.category_multiplier = category_multiplier
        self.reviewer_weight     = reviewer_weight
        self.seasonal_multiplier = seasonal_multiplier
        self.decay_rate          = decay_rate
        self.raw_points          = raw_points
        self.quarters_elapsed    = quarters_elapsed
        self.effective_points    = effective_points

    def as_dict(self) -> dict:
        return {
            "rating":               self.rating,
            "category_code":        self.category_code,
            "category_multiplier":  self.category_multiplier,
            "reviewer_weight":      self.reviewer_weight,
            "seasonal_multiplier":  self.seasonal_multiplier,
            "decay_rate":           self.decay_rate,
            "raw_points":           round(self.raw_points,     4),
            "quarters_elapsed":     self.quarters_elapsed,
            "effective_points":     round(self.effective_points, 4),
        }


# ──────────────────────────────────────────────────────────────
# 3.  PUBLIC API
# ──────────────────────────────────────────────────────────────

def calculate_points(
    *,
    rating:              int,
    category_multiplier: float,         # from review_categories.multiplier
    reviewer_weight:     float,         # from roles.reviewer_weight
    seasonal_multiplier: float,         # from seasonal_multipliers.multiplier
    decay_rate:          float,         # from points_config where config_key='DECAY_RATE'
    review_dt:           datetime,      # when the review was written
    reference_dt:        datetime | None = None,   # decay reference point (default: now)
    category_code:       str = "",      # for logging / audit only
) -> PointsResult:
    """
    Pure calculation entry point.

    All multipliers must be pre-resolved by the service layer (from DB).
    This function has no I/O dependencies.

    Parameters
    ----------
    rating               : int   – 1–5
    category_multiplier  : float – resolved from review_categories table
    reviewer_weight      : float – resolved from roles table
    seasonal_multiplier  : float – resolved from seasonal_multipliers table
    decay_rate           : float – resolved from points_config table
    review_dt            : datetime – when the review was created
    reference_dt         : datetime – decay reference point (default: now)
    category_code        : str   – label for logging, not used in maths

    Returns
    -------
    PointsResult with all intermediate values populated.
    """
    raw = rating * category_multiplier * reviewer_weight * seasonal_multiplier
    q   = quarters_elapsed(review_dt, reference_dt)
    eff = apply_decay(raw, q, decay_rate)

    return PointsResult(
        rating=rating,
        category_code=category_code,
        category_multiplier=category_multiplier,
        reviewer_weight=reviewer_weight,
        seasonal_multiplier=seasonal_multiplier,
        decay_rate=decay_rate,
        raw_points=raw,
        quarters_elapsed=q,
        effective_points=eff,
    )