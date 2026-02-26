"""Shared fixtures and factory helpers for analytics tests."""
from types import SimpleNamespace
from datetime import datetime, timezone
from uuid import uuid4


def make_employee(
    employee_id=None,
    username="john.doe",
    designation_name="Senior Developer",
    department_name="Engineering",
):
    """Return a mock employee with nested designation & department."""
    return SimpleNamespace(
        employee_id=employee_id or str(uuid4()),
        username=username,
        designations_employees_designation_idTodesignations=SimpleNamespace(
            designation_name=designation_name
        ),
        departments_employees_department_idTodepartments=SimpleNamespace(
            department_name=department_name
        ),
    )


def make_wallet(available=1500, redeemed=500, total=2000, wallet_id=None, employee_id=None):
    """Return a mock wallet object."""
    return SimpleNamespace(
        wallet_id=wallet_id or str(uuid4()),
        employee_id=employee_id or str(uuid4()),
        available_points=available,
        redeemed_points=redeemed,
        total_earned_points=total,
    )


def make_transaction(is_credit=True, amount=100, description="Performance bonus"):
    """Return a mock transaction with nested transaction_types."""
    return SimpleNamespace(
        transaction_id=str(uuid4()),
        amount=amount,
        description=description,
        transaction_at=datetime.now(timezone.utc),
        transaction_types=SimpleNamespace(is_credit=is_credit),
    )


def make_review(reviewer_username="jane.smith", rating=5, comment="Excellent work"):
    """Return a mock review with nested reviewer employee."""
    return SimpleNamespace(
        review_id=str(uuid4()),
        rating=rating,
        comment=comment,
        review_at=datetime.now(timezone.utc),
        employees_reviews_reviewer_idToemployees=SimpleNamespace(
            username=reviewer_username,
        ),
    )


def make_leaderboard_entry(
    username="alice",
    department_name="Engineering",
    total_earned_points=5000,
    employee_id=None,
):
    """Return a mock wallet with nested employee + department for leaderboard."""
    eid = employee_id or str(uuid4())
    return SimpleNamespace(
        wallet_id=str(uuid4()),
        employee_id=eid,
        total_earned_points=total_earned_points,
        employees_wallets_employee_idToemployees=SimpleNamespace(
            employee_id=eid,
            username=username,
            departments_employees_department_idTodepartments=SimpleNamespace(
                department_name=department_name
            ),
        ),
    )
