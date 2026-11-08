"""Enumerated worker profiles. The ONLY place worker limits are defined (constants, not input).

A caller selects a profile by name; it can never supply or raise a limit. Resource numbers are
consumed by the Docker backend in M1.5-2b; 2a uses only ``max_wall_timeout_s``.
"""

from dataclasses import dataclass
from enum import StrEnum


class WorkerKind(StrEnum):
    AGENT = "agent"
    VERIFY = "verify"


class ImageAlias(StrEnum):
    """Logical image names. The broker maps them to pinned digests it owns (2b); never a ref."""

    AGENT_BASE = "agent-base"
    VERIFY_BASE = "verify-base"


class Profile(StrEnum):
    AGENT_STANDARD = "agent-standard"
    VERIFY_STANDARD = "verify-standard"


@dataclass(frozen=True)
class ProfileLimits:
    kind: WorkerKind
    image_alias: ImageAlias
    max_wall_timeout_s: int
    memory_mb: int
    cpus: float
    pids: int
    disk_mb: int
    # "none" = no network at all. Provider egress for agents is undecided (D1) and NOT enabled.
    network: str


PROFILES: dict[Profile, ProfileLimits] = {
    Profile.AGENT_STANDARD: ProfileLimits(
        kind=WorkerKind.AGENT,
        image_alias=ImageAlias.AGENT_BASE,
        max_wall_timeout_s=1800,
        memory_mb=2048,
        cpus=1.0,
        pids=256,
        disk_mb=2048,
        network="none",
    ),
    Profile.VERIFY_STANDARD: ProfileLimits(
        kind=WorkerKind.VERIFY,
        image_alias=ImageAlias.VERIFY_BASE,
        max_wall_timeout_s=900,
        memory_mb=1024,
        cpus=1.0,
        pids=128,
        disk_mb=1024,
        network="none",
    ),
}
