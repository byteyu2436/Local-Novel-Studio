from dataclasses import dataclass
from typing import Literal

GpuPresence = Literal["ok", "absent", "probe_failed"]


@dataclass(frozen=True)
class RamSnapshot:
    ok: bool
    total_bytes: int | None = None
    available_bytes: int | None = None
    message: str = ""


@dataclass(frozen=True)
class GpuSnapshot:
    presence: GpuPresence
    name: str | None = None
    memory_total_mib: int | None = None
    memory_used_mib: int | None = None
    memory_free_mib: int | None = None
    message: str = ""
