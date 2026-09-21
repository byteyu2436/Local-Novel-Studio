from __future__ import annotations

from dataclasses import dataclass

from app.domain.chapter_detect import ChapterDetection, ChapterShape
from app.domain.importing import TXT_PREVIEW_CHARS, ImportValidationError

CANDIDATE_PREVIEW_CHARS = 240


@dataclass(frozen=True, slots=True)
class ChapterCandidate:
    candidate_id: str
    sequence: int
    original_label: str
    title_candidate: str
    start_offset: int
    end_offset: int
    confidence: float
    classification: ChapterShape


@dataclass(frozen=True, slots=True)
class DetectionResult:
    import_source_id: str
    checksum: str
    classification: ChapterShape
    candidates: tuple[ChapterCandidate, ...]
    warnings: tuple[str, ...]
    normalized_char_count: int


def validate_span(text: str, start: int, end: int) -> None:
    if start < 0 or end < 0 or start >= end or end > len(text):
        raise ImportValidationError(
            "candidate_offset_invalid",
            "Candidate offsets must stay inside the normalized text range.",
        )


def validate_candidates(text: str, candidates: tuple[ChapterCandidate, ...]) -> None:
    previous_end = 0
    seen_starts: list[int] = []
    for candidate in sorted(candidates, key=lambda item: (item.start_offset, item.end_offset)):
        validate_span(text, candidate.start_offset, candidate.end_offset)
        if candidate.start_offset < previous_end:
            raise ImportValidationError(
                "candidate_offset_overlap",
                "Candidate offsets overlap and cannot be confirmed.",
            )
        seen_starts.append(candidate.start_offset)
        previous_end = candidate.end_offset


def slice_normalized_text(text: str, start: int, end: int) -> str:
    validate_span(text, start, end)
    return text[start:end]


def candidate_preview(text: str, start: int, end: int) -> str:
    body = slice_normalized_text(text, start, end)
    limit = min(CANDIDATE_PREVIEW_CHARS, TXT_PREVIEW_CHARS)
    return body[:limit]


def candidates_from_detection(
    text: str,
    detection: ChapterDetection,
) -> tuple[tuple[ChapterCandidate, ...], tuple[str, ...]]:
    warnings = list(detection.warnings)
    if detection.shape is ChapterShape.UNSTRUCTURED or not detection.headings:
        if not text:
            raise ImportValidationError("txt_empty", "Normalized text is empty.")
        candidate = ChapterCandidate(
            candidate_id="c1",
            sequence=1,
            original_label="",
            title_candidate="",
            start_offset=0,
            end_offset=len(text),
            confidence=0.2,
            classification=ChapterShape.UNSTRUCTURED,
        )
        validate_candidates(text, (candidate,))
        return (candidate,), tuple(warnings)

    starts = [heading.start for heading in detection.headings]
    if starts[0] > 0:
        starts[0] = 0
        warnings.append("preamble_attached_to_first_chapter")
    bounds = [*starts, len(text)]
    built: list[ChapterCandidate] = []
    for index, heading in enumerate(detection.headings):
        start = bounds[index]
        end = bounds[index + 1]
        built.append(
            ChapterCandidate(
                candidate_id=f"c{index + 1}",
                sequence=heading.sequence,
                original_label=heading.original_label,
                title_candidate=heading.title_candidate,
                start_offset=start,
                end_offset=end,
                confidence=heading.confidence,
                classification=detection.shape,
            )
        )
    candidates = tuple(built)
    validate_candidates(text, candidates)
    return candidates, tuple(warnings)
