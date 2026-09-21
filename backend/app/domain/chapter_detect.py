from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

_DIGIT = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_UNIT = {"十": 10, "百": 100, "千": 1000, "万": 10_000}

_HEADING = re.compile(
    r"^(?P<label>第(?P<cn>[一二三四五六七八九十百千万零〇两0-9]+)(?:章|回)"
    r"|Chapter\s+(?P<en>\d+))"
    r"(?:[ \t:：\-—]+(?P<title>[^\n]*?)|[ \t]*)?$",
    re.IGNORECASE | re.MULTILINE,
)


class ChapterShape(StrEnum):
    SINGLE = "single"
    MULTI = "multi"
    UNSTRUCTURED = "unstructured"


@dataclass(frozen=True, slots=True)
class ChapterHeading:
    start: int
    end: int
    sequence: int
    original_label: str
    title_candidate: str
    confidence: float


@dataclass(frozen=True, slots=True)
class ChapterDetection:
    shape: ChapterShape
    headings: tuple[ChapterHeading, ...]
    warnings: tuple[str, ...]

    @property
    def classification(self) -> str:
        return self.shape.value


class ChapterDetector(Protocol):
    """Extensible chapter-structure detector. v0.2 uses rules, not an LLM."""

    def detect(self, text: str) -> ChapterDetection: ...


def chinese_int(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    total = 0
    current = 0
    for char in token:
        if char in _DIGIT:
            current = _DIGIT[char]
            continue
        unit = _UNIT.get(char)
        if unit is None:
            return None
        if current == 0:
            current = 1
        if unit == 10_000:
            total = (total + current) * unit
        else:
            total += current * unit
        current = 0
    return total + current


def _title_candidate(raw: str | None) -> str:
    return (raw or "").strip()


def parse_chapter_headings(text: str) -> tuple[ChapterHeading, ...]:
    found: list[ChapterHeading] = []
    for match in _HEADING.finditer(text):
        label = match.group("label")
        cn = match.group("cn")
        en = match.group("en")
        sequence = chinese_int(cn) if cn else int(en)
        if sequence is None or sequence <= 0:
            continue
        line = match.group(0).strip()
        if len(line) > 80:
            continue
        found.append(
            ChapterHeading(
                start=match.start(),
                end=match.end(),
                sequence=sequence,
                original_label=label.strip(),
                title_candidate=_title_candidate(match.group("title")),
                confidence=0.95 if match.start() == 0 or text[match.start() - 1] == "\n" else 0.6,
            )
        )
    return tuple(found)


def classify_headings(headings: tuple[ChapterHeading, ...]) -> tuple[ChapterShape, tuple[str, ...]]:
    if not headings:
        return ChapterShape.UNSTRUCTURED, ("no_chapter_boundary",)
    if len(headings) == 1:
        return ChapterShape.SINGLE, ()
    return ChapterShape.MULTI, ()


class RuleChapterDetector:
    """Line-start heading detector. Does not invent chapters from paragraphs."""

    def detect(self, text: str) -> ChapterDetection:
        headings = parse_chapter_headings(text)
        shape, warnings = classify_headings(headings)
        return ChapterDetection(shape=shape, headings=headings, warnings=warnings)


DEFAULT_CHAPTER_DETECTOR: ChapterDetector = RuleChapterDetector()


def detect_chapter_structure(
    text: str,
    detector: ChapterDetector | None = None,
) -> ChapterDetection:
    active = DEFAULT_CHAPTER_DETECTOR if detector is None else detector
    return active.detect(text)
