import re
from dataclasses import dataclass
from hashlib import sha256

_SCENE = re.compile(r"(?m)^(?:场景[:：]?.*|第[0-9一二三四五六七八九十百]+场.*|Scene\b.*)$")
_SENTENCE = re.compile(r"[^。！？!?;；.]*[。！？!?;；.]|[^。！？!?;；.]+$")


@dataclass(frozen=True)
class ChunkingProfile:
    version: str = "chunking.v1"
    target_min_tokens: int = 600
    target_max_tokens: int = 900
    overlap_tokens: int = 100

    def __post_init__(self) -> None:
        if self.target_max_tokens < 1:
            raise ValueError("target_max_tokens must be positive")
        if self.overlap_tokens < 0 or self.overlap_tokens >= self.target_max_tokens:
            raise ValueError("overlap_tokens must be smaller than target_max_tokens")


@dataclass(frozen=True)
class ChunkPiece:
    index: int
    text: str
    start_offset: int
    end_offset: int
    overlap_tokens: int
    chunk_type: str


def estimate_tokens(text: str) -> int:
    """Approximate tokens. One CJK character counts as one token."""

    tokens = 0
    index = 0
    while index < len(text):
        char = text[index]
        if "\u4e00" <= char <= "\u9fff":
            tokens += 1
            index += 1
            continue
        if char.isspace():
            index += 1
            continue
        end = index + 1
        while (
            end < len(text) and not text[end].isspace() and not ("\u4e00" <= text[end] <= "\u9fff")
        ):
            end += 1
        tokens += max(1, (end - index + 3) // 4)
        index = end
    return max(tokens, 1 if text else 0)


def chunk_identity(
    *,
    novel_id: str,
    chapter_id: str,
    source_version_id: str,
    chunking_version: str,
    index: int,
    text_checksum: str,
) -> str:
    raw = "\n".join(
        [novel_id, chapter_id, source_version_id, chunking_version, str(index), text_checksum]
    )
    return sha256(raw.encode()).hexdigest()


def text_checksum(text: str) -> str:
    return sha256(text.encode()).hexdigest()


def chunk_text(body: str, profile: ChunkingProfile) -> list[ChunkPiece]:
    """Split Canon text on scene, paragraph, then sentence boundaries."""

    if not body.strip():
        return []
    pieces: list[ChunkPiece] = []
    for scene_start, scene_end, scene_type in _scenes(body):
        spans = _atomic_spans(
            body,
            scene_start,
            scene_end,
            profile.target_min_tokens,
            profile.target_max_tokens,
        )
        cursor = scene_start
        span_index = 0
        previous_end = scene_start
        while cursor < scene_end:
            end, span_index = _pack(body, cursor, spans, span_index, profile.target_max_tokens)
            if end <= cursor:
                break
            if end <= previous_end:
                cursor = end
                continue
            overlap = estimate_tokens(body[cursor:previous_end]) if cursor < previous_end else 0
            pieces.append(
                ChunkPiece(
                    index=len(pieces),
                    text=body[cursor:end],
                    start_offset=cursor,
                    end_offset=end,
                    overlap_tokens=overlap,
                    chunk_type=scene_type,
                )
            )
            if end >= scene_end:
                break
            previous_end = end
            nxt = _rewind(body, end, profile.overlap_tokens)
            nxt = max(scene_start, nxt)
            cursor = end if nxt <= cursor else nxt
    return pieces


def _pack(
    body: str,
    cursor: int,
    spans: list[tuple[int, int]],
    span_index: int,
    max_tokens: int,
) -> tuple[int, int]:
    end = cursor
    while span_index < len(spans) and spans[span_index][1] <= cursor:
        span_index += 1
    while span_index < len(spans):
        _span_start, span_end = spans[span_index]
        if span_end <= cursor:
            span_index += 1
            continue
        if estimate_tokens(body[cursor:span_end]) > max_tokens:
            if end > cursor:
                break
            return _windows(body, cursor, span_end, max_tokens)[0][1], span_index
        end = span_end
        span_index += 1
    return end, span_index


def _scenes(body: str) -> list[tuple[int, int, str]]:
    marks = [match.start() for match in _SCENE.finditer(body)]
    if not marks:
        return [(0, len(body), "chapter")]
    bounds = marks + [len(body)]
    if marks[0] > 0:
        bounds = [0, *bounds]
    scenes: list[tuple[int, int, str]] = []
    for start, end in zip(bounds, bounds[1:], strict=False):
        if start < end and body[start:end].strip():
            kind = "scene" if _SCENE.match(body[start:]) else "chapter"
            scenes.append((start, end, kind))
    return scenes or [(0, len(body), "chapter")]


def _atomic_spans(
    body: str, start: int, end: int, min_tokens: int, max_tokens: int
) -> list[tuple[int, int]]:
    paragraphs = _merge_short(_paragraphs(body, start, end), body, min_tokens, max_tokens)
    spans: list[tuple[int, int]] = []
    for para_start, para_end in paragraphs:
        if estimate_tokens(body[para_start:para_end]) <= max_tokens:
            spans.append((para_start, para_end))
            continue
        for sentence_start, sentence_end in _sentences(body, para_start, para_end):
            spans.extend(_windows(body, sentence_start, sentence_end, max_tokens))
    return spans or [(start, end)]


def _merge_short(
    parts: list[tuple[int, int]], body: str, min_tokens: int, max_tokens: int
) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    buf_start: int | None = None
    buf_end: int | None = None
    for start, end in parts:
        if buf_start is None or buf_end is None:
            buf_start, buf_end = start, end
            continue
        current = estimate_tokens(body[buf_start:buf_end])
        combined = estimate_tokens(body[buf_start:end])
        if current < min_tokens and combined <= max_tokens:
            buf_end = end
            continue
        merged.append((buf_start, buf_end))
        buf_start, buf_end = start, end
    if buf_start is not None and buf_end is not None:
        merged.append((buf_start, buf_end))
    return merged


def _paragraphs(body: str, start: int, end: int) -> list[tuple[int, int]]:
    region = body[start:end]
    splitter = "\n\n" if "\n\n" in region else "\n"
    parts: list[tuple[int, int]] = []
    cursor = start
    for block in region.split(splitter):
        block_end = cursor + len(block)
        if body[cursor:block_end].strip():
            parts.append((cursor, block_end))
        cursor = block_end + len(splitter)
    return parts or [(start, end)]


def _sentences(body: str, start: int, end: int) -> list[tuple[int, int]]:
    region = body[start:end]
    parts: list[tuple[int, int]] = []
    cursor = start
    for match in _SENTENCE.finditer(region):
        sentence = match.group(0)
        if not sentence:
            continue
        sentence_end = cursor + len(sentence)
        if sentence.strip():
            parts.append((cursor, sentence_end))
        cursor = sentence_end
    return parts or [(start, end)]


def _windows(body: str, start: int, end: int, max_tokens: int) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        window_end = cursor
        while window_end < end and estimate_tokens(body[cursor : window_end + 1]) <= max_tokens:
            window_end += 1
        if window_end == cursor:
            window_end = min(end, cursor + 1)
        windows.append((cursor, window_end))
        cursor = window_end
    return windows


def _rewind(body: str, end: int, overlap_tokens: int) -> int:
    if overlap_tokens <= 0:
        return end
    cursor = end
    while cursor > 0 and estimate_tokens(body[cursor - 1 : end]) <= overlap_tokens:
        cursor -= 1
    return cursor
