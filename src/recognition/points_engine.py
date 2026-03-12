"""
points_engine.py
────────────────
Stateless points calculation engine for the Recognition Service.

All multiplier values are resolved from the database by the service layer
and passed in as plain floats.  The engine itself has zero DB / IO dependencies
and remains trivially unit-testable.

Formula
-------
    raw_points = sum(category_multipliers) × reviewer_weight

Multi-category
--------------
When a reviewer selects multiple category tags, the service layer resolves each
category's multiplier from the DB, sums them, and passes the total here as
`total_category_multiplier`.  Each additional tag genuinely adds weight —
selecting INNOVATION (1.4) + TEAMWORK (1.2) yields a total multiplier of 2.6,
giving raw_points = 2.6 × reviewer_weight.

What lives in the DB
--------------------
| Value                          | Table / column                          |
|--------------------------------|-----------------------------------------|
| Per-category multiplier        | review_categories.multiplier            |
| Per-tag snapshot               | review_category_tags.multiplier_snapshot|
| Reviewer weight                | roles.reviewer_weight                   |

Note: rating and seasonal_multiplier are NOT part of the points formula.
rating is stored on the review record for display purposes only.
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
        "category_code",
        "total_category_multiplier",
        "reviewer_weight",
        "raw_points",
    )

    def __init__(
        self,
        category_code: str,
        total_category_multiplier: float,
        reviewer_weight: float,
        raw_points: float,
    ) -> None:
        self.category_code             = category_code
        self.total_category_multiplier = total_category_multiplier
        self.reviewer_weight           = reviewer_weight
        self.raw_points                = raw_points

    def as_dict(self) -> dict:
        return {
            "category_code":             self.category_code,
            "total_category_multiplier": self.total_category_multiplier,
            "reviewer_weight":           self.reviewer_weight,
            "raw_points":                round(self.raw_points, 4),
        }


# ──────────────────────────────────────────────────────────────
# 2.  PUBLIC API
# ──────────────────────────────────────────────────────────────

def calculate_points(
    *,
    total_category_multiplier: float,   # sum of all selected category multipliers
    reviewer_weight:           float,   # from roles.reviewer_weight
    category_code:             str = "", # for logging / audit only
) -> PointsResult:
    """
    Pure calculation entry point.

    All multipliers must be pre-resolved by the service layer (from DB).
    This function has no I/O dependencies.

    Parameters
    ----------
    total_category_multiplier : float – sum of selected review_categories multipliers
    reviewer_weight           : float – resolved from roles table
    category_code             : str   – label(s) for logging, not used in maths

    Returns
    -------
    PointsResult with all intermediate values populated.
    """
    raw = total_category_multiplier * reviewer_weight

    return PointsResult(
        category_code=category_code,
        total_category_multiplier=total_category_multiplier,
        reviewer_weight=reviewer_weight,
        raw_points=raw,
    )