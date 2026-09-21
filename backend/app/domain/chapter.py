from enum import StrEnum


class VersionKind(StrEnum):
    ORIGINAL = "ORIGINAL"
    DRAFT = "DRAFT"
    ACCEPTED = "ACCEPTED"


class TitleSource(StrEnum):
    ORIGINAL = "original"
    USER = "user"
    GENERATED = "generated"
    FALLBACK = "fallback"
