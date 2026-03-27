"""Staff user model for sovereign runtime auth."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.database import Base


class StaffRole(str, Enum):
    """Hierarchy for Command Center access control."""

    SUPER_ADMIN = "super_admin"
    MANAGER = "manager"
    REVIEWER = "reviewer"


STAFF_ROLE_VALUES: tuple[str, ...] = tuple(role.value for role in StaffRole)


class StaffUser(Base):
    """Staff/admin identity stored inside the sovereign Postgres runtime."""

    __tablename__ = "staff_users"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[StaffRole] = mapped_column(
        SqlEnum(
            StaffRole,
            name="staff_role",
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            values_callable=lambda enum_cls: [role.value for role in enum_cls],
        ),
        index=True,
        nullable=False,
        default=StaffRole.SUPER_ADMIN,
        server_default=StaffRole.SUPER_ADMIN.value,
    )
    permissions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    notification_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notification_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notify_urgent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    notify_workorders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=datetime.utcnow,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=text("now()"),
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<StaffUser {self.full_name} ({self.role.value})>"
