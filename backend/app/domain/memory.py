from enum import StrEnum


class ForeshadowingStatus(StrEnum):
    PLANTED = "planted"
    REINFORCED = "reinforced"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


class MemorySubjectKind(StrEnum):
    CHARACTER = "character"
    RELATIONSHIP = "relationship"
    EVENT = "event"
    TIMELINE = "timeline"
    FORESHADOWING = "foreshadowing"
    WORLD_FACT = "world_fact"
    STYLE_PROFILE = "style_profile"


class FactOrigin(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"


class FactStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


FORESHADOWING_STATUSES = tuple(item.value for item in ForeshadowingStatus)
MEMORY_SUBJECT_KINDS = tuple(item.value for item in MemorySubjectKind)
FACT_ORIGINS = tuple(item.value for item in FactOrigin)
FACT_STATUSES = tuple(item.value for item in FactStatus)


class MemoryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
