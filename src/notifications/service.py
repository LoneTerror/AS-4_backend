import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from prisma import Prisma

from .schemas import NotificationType

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Thin, async-first service for creating and managing notifications.

    All timestamps are timezone-aware (UTC).  The service owns no state
    beyond the injected Prisma client, making it safe to instantiate once
    at startup and share across request handlers.
    """

    def __init__(self, db: Prisma) -> None:
        self._db = db

    # ── Write ──────────────────────────────────────────────────────────────────

    async def create_notification(
        self,
        *,
        employee_id: UUID | str,
        title: str,
        message: str,
        type: NotificationType,
    ) -> dict:
        """
        Persist a new notification row.

        Returns the created record as a plain dict so callers never have to
        import Prisma model types.
        """
        record = await self._db.notifications.create(
            data={
                "employee_id": str(employee_id),
                "title": title,
                "message": message,
                "type": type.value,
                "is_read": False,
                "email_sent": False,
                "created_at": datetime.now(tz=timezone.utc),
            }
        )
        logger.debug(
            "Notification created: id=%s employee=%s type=%s",
            record.notification_id,
            employee_id,
            type,
        )
        return record.model_dump()

    # ── Read ───────────────────────────────────────────────────────────────────

    async def get_notifications(
        self,
        *,
        employee_id: UUID | str,
        limit: int = 50,
        unread_only: bool = False,
    ) -> list[dict]:
        where: dict = {"employee_id": str(employee_id)}
        if unread_only:
            where["is_read"] = False

        records = await self._db.notifications.find_many(
            where=where,
            order={"created_at": "desc"},
            take=limit,
        )
        return [r.model_dump() for r in records]

    async def get_unread_count(self, *, employee_id: UUID | str) -> int:
        return await self._db.notifications.count(
            where={"employee_id": str(employee_id), "is_read": False}
        )

    # ── Mutations ──────────────────────────────────────────────────────────────

    async def mark_as_read(
        self,
        *,
        notification_id: UUID | str,
        employee_id: UUID | str,
    ) -> Optional[dict]:
        existing = await self._db.notifications.find_first(
            where={
                "notification_id": str(notification_id),
                "employee_id": str(employee_id),
            }
        )
        if existing is None:
            return None

        updated = await self._db.notifications.update(
            where={"notification_id": str(notification_id)},
            data={
                "is_read": True,
                "read_at": datetime.now(tz=timezone.utc),
            },
        )
        return updated.model_dump() if updated else None

    async def mark_all_as_read(self, *, employee_id: UUID | str) -> int:
        result = await self._db.notifications.update_many(
            where={"employee_id": str(employee_id), "is_read": False},
            data={"is_read": True},
        )
        return result

    # ── Celebrations ───────────────────────────────────────────────────────────

    async def get_employees_with_celebrations_today(self) -> list[dict]:
        """
        Return employees whose birthday OR work anniversary falls today.

        Schema facts used:
          - employees.date_of_birth      DateTime? @db.Date  (new — via migration.sql)
          - employees.date_of_joining    DateTime  @db.Date  (existing)
          - employees.username           the display name field (no separate first/last)
          - employees.email              recipient address
          - Active employees only: filtered via the status_master relation
            (status_master_employees_status_idTostatus_master.status_code = "ACTIVE")
            because employees has no boolean is_active column.

        Each dict contains:
            employee_id, username, email,
            celebration_type  ("BIRTHDAY" | "WORK_ANNIVERSARY"),
            years             (int for anniversaries, None for birthdays)
        """
        from datetime import date

        today = date.today()
        month, day = today.month, today.day

        # Relation name comes directly from the @relation() annotation in schema.prisma:
        #   status_master_employees_status_idTostatus_master
        employees = await self._db.employees.find_many(
            where={
                "status_master_employees_status_idTostatus_master": {
                    "is": {"status_code": "ACTIVE"}
                }
            },
        )

        celebrants: list[dict] = []

        for emp in employees:
            # ── Birthday check ───────────────────────────────────────────────
            dob = emp.date_of_birth          # datetime.date | None
            if (
                dob is not None
                and dob.month == month
                and dob.day == day
            ):
                celebrants.append({
                    "employee_id": emp.employee_id,
                    "username": emp.username,
                    "email": emp.email,
                    "celebration_type": "BIRTHDAY",
                    "years": None,
                })

            # ── Work anniversary check ───────────────────────────────────────
            doj = emp.date_of_joining        # datetime.date (non-nullable in schema)
            if (
                doj.month == month
                and doj.day == day
                and doj.year != today.year   # skip the actual hire-day
            ):
                years = today.year - doj.year
                celebrants.append({
                    "employee_id": emp.employee_id,
                    "username": emp.username,
                    "email": emp.email,
                    "celebration_type": "WORK_ANNIVERSARY",
                    "years": years,
                })

        logger.debug("Celebrations today: %d employee(s)", len(celebrants))
        return celebrants

    async def celebration_already_sent_today(
        self,
        *,
        employee_id: UUID | str,
        celebration_type: str,  # "BIRTHDAY" | "WORK_ANNIVERSARY"
    ) -> bool:
        """
        Idempotency guard — returns True if a CELEBRATION notification of this
        type was already created for this employee today.

        Prevents duplicate emails if the server restarts mid-day.
        """
        from datetime import date, datetime, timezone

        start_of_day = datetime.combine(date.today(), datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        existing = await self._db.notifications.find_first(
            where={
                "employee_id": str(employee_id),
                "type": "CELEBRATION",
                # The worker sets the title to the email subject, which always
                # contains "BIRTHDAY" or "WORK_ANNIVERSARY" as a substring.
                "title": {"contains": celebration_type},
                "created_at": {"gte": start_of_day},
            }
        )
        return existing is not None