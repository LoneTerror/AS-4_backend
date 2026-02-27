"""
points_engine.py
────────────────
Stateless points calculation engine for the Recognition Service.

All multiplier values are resolved from the database by the service layer
and passed in as plain floats.  The engine itself has zero DB / IO dependencies
and remains trivially unit-testable.

Formula
-------
    raw_points = rating × sum(category_multipliers) × reviewer_weight × seasonal_multiplier

Multi-category
--------------
When a reviewer selects multiple category tags, the service layer resolves each
category's multiplier from the DB, sums them, and passes the total here as
`total_category_multiplier`.  Each additional tag genuinely adds weight —
selecting INNOVATION (1.4) + TEAMWORK (1.2) yields a total multiplier of 2.6.

What lives in the DB
--------------------
| Value                          | Table / column                        |
|--------------------------------|---------------------------------------|
| Per-category multiplier        | review_categories.multiplier          |
| Per-tag snapshot               | review_category_tags.multiplier_snapshot|
| Reviewer weight                | roles.reviewer_weight                 |
| Seasonal multiplier            | seasonal_multipliers.multiplier       |

Note: reviews.category_multiplier has been removed. The total is derivable
by summing review_category_tags.multiplier_snapshot for a given review_id.
"""

from __future__ import annotations


# ──────────────────────────────────────────────────────────────
# 1.  RESULT CONTAINER
# ──────────────────────────────────────────────────────────────

class PointsResult:
    """
    Carries every intermediate value so callers can log / store all steps.

    category_code is a human-readable label (or comma-joined labels) for
    logging; it is not used in any calculation.
    """

    __slots__ = (
        "rating",
        "category_code",
        "total_category_multiplier",
        "reviewer_weight",
        "seasonal_multiplier",
        "raw_points",
    )

    def __init__(
        self,
        rating: int,
        category_code: str,
        total_category_multiplier: float,
        reviewer_weight: float,
        seasonal_multiplier: float,
        raw_points: float,
    ) -> None:
        self.rating                    = rating
        self.category_code             = category_code
        self.total_category_multiplier = total_category_multiplier
        self.reviewer_weight           = reviewer_weight
        self.seasonal_multiplier       = seasonal_multiplier
        self.raw_points                = raw_points

    def as_dict(self) -> dict:
        return {
            "rating":                    self.rating,
            "category_code":             self.category_code,
            "total_category_multiplier": self.total_category_multiplier,
            "reviewer_weight":           self.reviewer_weight,
            "seasonal_multiplier":       self.seasonal_multiplier,
            "raw_points":                round(self.raw_points, 4),
        }


# ──────────────────────────────────────────────────────────────
# 2.  PUBLIC API
# ──────────────────────────────────────────────────────────────

def calculate_points(
    *,
    rating:                    int,
    total_category_multiplier: float,   # sum of all selected category multipliers
    reviewer_weight:           float,   # from roles.reviewer_weight
    seasonal_multiplier:       float,   # from seasonal_multipliers.multiplier
    category_code:             str = "", # for logging / audit only
) -> PointsResult:
    """
    Pure calculation entry point.

    All multipliers must be pre-resolved by the service layer (from DB).
    This function has no I/O dependencies.

    Parameters
    ----------
    rating                    : int   – 1–5
    total_category_multiplier : float – sum of selected review_categories multipliers
    reviewer_weight           : float – resolved from roles table
    seasonal_multiplier       : float – resolved from seasonal_multipliers table
    category_code             : str   – label(s) for logging, not used in maths

    Returns
    -------
    PointsResult with all intermediate values populated.
    """
    raw = rating * total_category_multiplier * reviewer_weight * seasonal_multiplier

    return PointsResult(
        rating=rating,
        category_code=category_code,
        total_category_multiplier=total_category_multiplier,
        reviewer_weight=reviewer_weight,
        seasonal_multiplier=seasonal_multiplier,
        raw_points=raw,
    )