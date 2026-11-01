from typing import Any

from sqlalchemy import JSON, Boolean, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.project import StudioType


class Agent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "agents"

    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    studio_type: Mapped[StudioType] = mapped_column(
        Enum(StudioType, native_enum=False),
        nullable=False,
        index=True,
    )
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    available_tools: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    model_config_data: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=lambda: {"model_id": "claude-haiku-5-5", "temperature": 0.2},
        nullable=False,
    )
    execution_config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=lambda: {"timeout_seconds": 120, "max_retries": 1},
        nullable=False,
    )
    verification_requirements: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[str] = mapped_column(String(50), default="1.0.0", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
