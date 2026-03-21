"""
tests/test_points_engine.py
────────────────────────────
Pure unit tests for the stateless points calculation engine.
No mocks needed — the engine has zero I/O dependencies.
"""
from __future__ import annotations

import pytest
from src.recognition.points_engine import PointsResult, calculate_points


# ─────────────────────────────────────────────────────────────────────────────
# PointsResult
# ─────────────────────────────────────────────────────────────────────────────

class TestPointsResult:
    def test_slots_assigned_correctly(self):
        r = PointsResult(
            category_code="INNOVATION",
            total_category_multiplier=1.4,
            reviewer_weight=1.0,
            raw_points=1.4,
        )
        assert r.category_code             == "INNOVATION"
        assert r.total_category_multiplier == 1.4
        assert r.reviewer_weight           == 1.0
        assert r.raw_points                == 1.4

    def test_as_dict_returns_all_keys(self):
        r = PointsResult("CODE", 2.0, 1.5, 3.0)
        d = r.as_dict()
        assert set(d.keys()) == {
            "category_code", "total_category_multiplier",
            "reviewer_weight", "raw_points",
        }

    def test_as_dict_rounds_raw_points_to_4dp(self):
        r = PointsResult("X", 1.0, 1.0 / 3, 1.0 / 3)
        d = r.as_dict()
        assert d["raw_points"] == round(1.0 / 3, 4)

    def test_as_dict_exact_values(self):
        r = PointsResult("A,B", 2.6, 1.2, 3.12)
        d = r.as_dict()
        assert d["category_code"]             == "A,B"
        assert d["total_category_multiplier"] == 2.6
        assert d["reviewer_weight"]           == 1.2
        assert d["raw_points"]                == 3.12


# ─────────────────────────────────────────────────────────────────────────────
# calculate_points — happy path
# ─────────────────────────────────────────────────────────────────────────────

class TestCalculatePoints:
    def test_single_category_default_weight(self):
        result = calculate_points(
            total_category_multiplier=1.4,
            reviewer_weight=1.0,
        )
        assert isinstance(result, PointsResult)
        assert result.raw_points == pytest.approx(1.4)

    def test_multi_category_summed_multiplier(self):
        """INNOVATION(1.4) + TEAMWORK(1.2) = 2.6 × 1.0"""
        result = calculate_points(
            total_category_multiplier=2.6,
            reviewer_weight=1.0,
        )
        assert result.raw_points == pytest.approx(2.6)

    def test_reviewer_weight_applied(self):
        result = calculate_points(
            total_category_multiplier=2.0,
            reviewer_weight=1.5,
        )
        assert result.raw_points == pytest.approx(3.0)

    def test_fractional_weight(self):
        result = calculate_points(
            total_category_multiplier=1.0,
            reviewer_weight=0.75,
        )
        assert result.raw_points == pytest.approx(0.75)

    def test_category_code_label_stored_but_not_used(self):
        r1 = calculate_points(total_category_multiplier=1.0, reviewer_weight=1.0, category_code="LABEL")
        r2 = calculate_points(total_category_multiplier=1.0, reviewer_weight=1.0, category_code="OTHER")
        assert r1.raw_points == r2.raw_points
        assert r1.category_code == "LABEL"
        assert r2.category_code == "OTHER"

    def test_category_code_defaults_to_empty_string(self):
        r = calculate_points(total_category_multiplier=1.0, reviewer_weight=1.0)
        assert r.category_code == ""

    def test_five_category_max(self):
        """Max 5 categories: 1.4+1.3+1.2+1.1+1.0 = 6.0"""
        result = calculate_points(
            total_category_multiplier=6.0,
            reviewer_weight=1.0,
            category_code="A,B,C,D,E",
        )
        assert result.raw_points == pytest.approx(6.0)

    def test_result_fields_match_inputs(self):
        r = calculate_points(
            total_category_multiplier=2.5,
            reviewer_weight=1.2,
            category_code="OWNERSHIP,INNOVATION",
        )
        assert r.total_category_multiplier == 2.5
        assert r.reviewer_weight           == 1.2

    def test_zero_multiplier(self):
        r = calculate_points(total_category_multiplier=0.0, reviewer_weight=1.5)
        assert r.raw_points == pytest.approx(0.0)

    def test_zero_weight(self):
        r = calculate_points(total_category_multiplier=1.4, reviewer_weight=0.0)
        assert r.raw_points == pytest.approx(0.0)

    def test_large_values(self):
        r = calculate_points(total_category_multiplier=100.0, reviewer_weight=5.0)
        assert r.raw_points == pytest.approx(500.0)

    def test_returns_points_result_type(self):
        r = calculate_points(total_category_multiplier=1.0, reviewer_weight=1.0)
        assert isinstance(r, PointsResult)

    def test_formula_is_multiplication(self):
        """raw = total_category_multiplier × reviewer_weight"""
        m, w = 3.7, 1.3
        r = calculate_points(total_category_multiplier=m, reviewer_weight=w)
        assert r.raw_points == pytest.approx(m * w, rel=1e-9)

    def test_as_dict_round_trip(self):
        r = calculate_points(total_category_multiplier=1.6, reviewer_weight=1.25, category_code="TEAMWORK")
        d = r.as_dict()
        assert d["raw_points"] == round(1.6 * 1.25, 4)
