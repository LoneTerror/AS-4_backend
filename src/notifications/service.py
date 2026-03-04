import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from prisma import Prisma

from .schemas import NotificationType

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, db: Prisma) -> None:
        self._db = db

    # ── Core create ───────────────────────────────────────────────────────────

    async def create_notification(
        self,
        *,
        employee_id: UUID | str,
        title: str,
        message: str,
        type: NotificationType,
    ) -> dict:
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

    # ── Bulk helpers ──────────────────────────────────────────────────────────

    async def create_bulk_notifications(
        self,
        *,
        employee_ids: list[UUID | str],
        title: str,
        message: str,
        type: NotificationType,
    ) -> list[dict]:
        """
        Create one notification row per employee_id.
        Runs sequentially — Prisma does not expose createMany with return values.
        The email worker will pick these up automatically.
        """
        records: list[dict] = []
        for eid in employee_ids:
            record = await self.create_notification(
                employee_id=eid,
                title=title,
                message=message,
                type=type,
            )
            records.append(record)
        logger.info(
            "Bulk notifications created: count=%d type=%s title=%r",
            len(records),
            type,
            title,
        )
        return records

    async def get_all_active_employee_ids(self) -> list[str]:
        """Return employee_id strings for every ACTIVE employee."""
        employees = await self._db.employees.find_many(
            include={"status_master_employees_status_idTostatus_master": True}
        )
        return [
            str(e.employee_id)
            for e in employees
            if (
                e.status_master_employees_status_idTostatus_master is not None
                and e.status_master_employees_status_idTostatus_master.status_code
                == "ACTIVE"
            )
        ]

    async def get_active_employee_ids_by_department(
        self, department_ids: list[UUID | str]
    ) -> list[str]:
        """Return employee_id strings for ACTIVE employees in the given departments."""
        dept_id_strs = [str(d) for d in department_ids]
        employees = await self._db.employees.find_many(
            where={"department_id": {"in": dept_id_strs}},
            include={"status_master_employees_status_idTostatus_master": True},
        )
        return [
            str(e.employee_id)
            for e in employees
            if (
                e.status_master_employees_status_idTostatus_master is not None
                and e.status_master_employees_status_idTostatus_master.status_code
                == "ACTIVE"
            )
        ]

    # ── Read / mark-read ─────────────────────────────────────────────────────

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

    # ── Celebration helpers ───────────────────────────────────────────────────

    async def get_employees_with_celebrations_today(self) -> list[dict]:
        from datetime import date

        today = date.today()
        month, day = today.month, today.day

        all_employees = await self._db.employees.find_many(
            include={"status_master_employees_status_idTostatus_master": True}
        )

        celebrants: list[dict] = []

        for emp in all_employees:
            status = emp.status_master_employees_status_idTostatus_master
            if status is None or status.status_code != "ACTIVE":
                continue

            dob = emp.date_of_birth
            if dob is not None and dob.month == month and dob.day == day:
                celebrants.append({
                    "employee_id": emp.employee_id,
                    "username": emp.username,
                    "email": emp.email,
                    "celebration_type": "BIRTHDAY",
                    "years": None,
                })

            doj = emp.date_of_joining
            if (
                doj is not None
                and doj.month == month
                and doj.day == day
                and doj.year != today.year
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
        celebration_type: str,
    ) -> bool:
        """
        Idempotency guard.

        The sentinel row is written to the CELEBRANT's employee_id with a
        title prefixed '[SENTINEL]' BEFORE the broadcast begins.
        We check only for that sentinel — NOT for regular broadcast rows —
        so that other celebrants' broadcast rows never trigger a false positive.
        """
        from datetime import date

        start_of_day = datetime.combine(date.today(), datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        existing = await self._db.notifications.find_first(
            where={
                "employee_id": str(employee_id),
                "type": "CELEBRATION",
                "title": {"startswith": "[SENTINEL]"},
                "message": {"contains": f"[{celebration_type}]"},
                "created_at": {"gte": start_of_day},
            }
        )
        return existing is not None

    async def create_sentinel(
        self,
        *,
        employee_id: UUID | str,
        celebration_type: str,
        celebrant_name: str,
    ) -> dict:
        """
        Write a sentinel row to the celebrant's account BEFORE broadcasting.
        Title format:  [SENTINEL] <name>
        Message format: [BIRTHDAY] or [WORK_ANNIVERSARY]
        This row is NEVER shown in the notification feed (filtered by router/service).
        """
        record = await self._db.notifications.create(
            data={
                "employee_id": str(employee_id),
                "title": f"[SENTINEL] {celebrant_name}",
                "message": f"[{celebration_type}] broadcast initiated",
                "type": NotificationType.CELEBRATION.value,
                "is_read": True,
                "email_sent": True,
                "created_at": datetime.now(tz=timezone.utc),
            }
        )
        return record.model_dump()