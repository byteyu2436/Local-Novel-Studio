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


def fallback_chapter_title(
    sequence: int, *, original_label: str = "", original_title: str = ""
) -> str:
    """Readable catalog title when the source heading has no semantic name."""

    label = original_label.strip()
    title = original_title.strip()
    if label and title:
        return f"{label} {title}"
    if title:
        return title
    if label:
        return label
    return f"第{sequence}章"


def resolve_chapter_title(
    *,
    sequence: int,
    original_label: str = "",
    original_title: str = "",
    display_title: str | None = None,
    title_source: TitleSource | str | None = None,
) -> tuple[str, TitleSource]:
    """Pick display_title and provenance. Generated titles are out of scope for v0.2."""

    if title_source is None:
        has_source_title = bool(original_title.strip() or original_label.strip())
        kind = TitleSource.ORIGINAL if has_source_title else TitleSource.FALLBACK
    else:
        kind = TitleSource(title_source)
    if kind is TitleSource.GENERATED:
        kind = TitleSource.FALLBACK
    explicit = (display_title or "").strip()
    if kind is TitleSource.USER and explicit:
        return explicit, TitleSource.USER
    if explicit and kind is not TitleSource.FALLBACK:
        return explicit, kind
    resolved = fallback_chapter_title(
        sequence, original_label=original_label, original_title=original_title
    )
    if original_title.strip() or original_label.strip():
        return resolved, TitleSource.ORIGINAL
    return resolved, TitleSource.FALLBACK
