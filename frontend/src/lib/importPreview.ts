export type ChapterClassification = "single" | "multi" | "unstructured";

export type PreviewDestination = "new_novel" | "append";

export type ChapterCandidate = {
  candidate_id: string;
  sequence: number;
  original_label: string;
  title_candidate: string;
  start_offset: number;
  end_offset: number;
  confidence: number;
  classification: ChapterClassification;
  preview_text: string;
};

export type DetectionResult = {
  import_source_id: string;
  checksum: string;
  classification: ChapterClassification;
  candidates: ChapterCandidate[];
  warnings: string[];
  normalized_char_count: number;
};

export type PreviewDraft = {
  import_source_id: string;
  checksum: string;
  classification: ChapterClassification;
  candidates: ChapterCandidate[];
  warnings: string[];
  destination: PreviewDestination;
  novel_id: string;
  unstructured_ack: boolean;
  confirmed: boolean;
  confirmedNovelId?: string;
  confirmedChapterId?: string;
};

export const PREVIEW_STORAGE_PREFIX = "lns.import-preview:";

export function previewStorageKey(sourceId: string): string {
  return `${PREVIEW_STORAGE_PREFIX}${sourceId}`;
}

export function classificationLabel(kind: ChapterClassification): string {
  if (kind === "single") return "单章节";
  if (kind === "multi") return "多章节";
  return "无明确章节结构";
}

export function isLowConfidence(candidate: ChapterCandidate): boolean {
  return candidate.confidence < 0.5;
}

export function mergeWithNext(
  candidates: ChapterCandidate[],
  index: number,
): ChapterCandidate[] | { error: string } {
  if (index < 0 || index >= candidates.length - 1) {
    return { error: "没有可合并的下一章。" };
  }
  const current = candidates[index];
  const next = candidates[index + 1];
  if (current.end_offset !== next.start_offset) {
    return { error: "只能合并相邻的原文范围。" };
  }
  const merged: ChapterCandidate = {
    ...current,
    end_offset: next.end_offset,
    title_candidate: current.title_candidate || next.title_candidate,
    preview_text: `${current.preview_text}\n${next.preview_text}`.trim(),
  };
  return [
    ...candidates.slice(0, index),
    merged,
    ...candidates.slice(index + 2),
  ];
}

export function splitAtRelativeOffset(
  candidates: ChapterCandidate[],
  index: number,
  relativeOffset: number,
): ChapterCandidate[] | { error: string } {
  const current = candidates[index];
  if (!current) return { error: "找不到要拆分的章节。" };
  const length = current.end_offset - current.start_offset;
  if (relativeOffset <= 0 || relativeOffset >= length) {
    return { error: "拆分位置必须落在该章正文内部。" };
  }
  const mid = current.start_offset + relativeOffset;
  const left: ChapterCandidate = {
    ...current,
    candidate_id: `${current.candidate_id}a`,
    end_offset: mid,
    preview_text: current.preview_text.slice(0, relativeOffset),
  };
  const right: ChapterCandidate = {
    ...current,
    candidate_id: `${current.candidate_id}b`,
    original_label: "",
    title_candidate: "",
    start_offset: mid,
    sequence: current.sequence + 1,
    preview_text: current.preview_text.slice(relativeOffset),
  };
  return [
    ...candidates.slice(0, index),
    left,
    right,
    ...candidates.slice(index + 1),
  ];
}

export function moveCandidate(
  candidates: ChapterCandidate[],
  index: number,
  direction: -1 | 1,
): ChapterCandidate[] | { error: string } {
  if (index < 0 || index >= candidates.length) {
    return { error: "无法再移动该章节。" };
  }
  const target = index + direction;
  if (target < 0 || target >= candidates.length) {
    return { error: "无法再移动该章节。" };
  }
  const next = [...candidates];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

export function setSequence(
  candidates: ChapterCandidate[],
  index: number,
  sequence: number,
): ChapterCandidate[] | { error: string } {
  if (!Number.isInteger(sequence) || sequence <= 0) {
    return { error: "章节序号必须是大于 0 的整数。" };
  }
  return candidates.map((item, itemIndex) =>
    itemIndex === index ? { ...item, sequence } : item,
  );
}

export function confirmBlockedReason(draft: {
  classification: ChapterClassification;
  destination: PreviewDestination;
  novel_id: string;
  unstructured_ack: boolean;
  candidates: ChapterCandidate[];
}): string | null {
  if (draft.candidates.length === 0) return "没有可确认的章节。";
  if (draft.classification === "unstructured" && !draft.unstructured_ack) {
    return "无明确结构的文本必须先确认切分建议。";
  }
  if (draft.destination === "append" && draft.novel_id.trim().length === 0) {
    return "追加到已有小说时请填写小说 ID。";
  }
  return null;
}

export function parseDetectionPayload(
  payload: unknown,
): DetectionResult | { error: string } {
  if (!payload || typeof payload !== "object") {
    return { error: "无法读取章节检测结果。" };
  }
  const body = payload as Partial<DetectionResult>;
  if (
    typeof body.import_source_id !== "string" ||
    !Array.isArray(body.candidates)
  ) {
    return { error: "无法读取章节检测结果。" };
  }
  const classification =
    body.classification === "single" || body.classification === "multi"
      ? body.classification
      : "unstructured";
  return {
    import_source_id: body.import_source_id,
    checksum: typeof body.checksum === "string" ? body.checksum : "",
    classification,
    warnings: Array.isArray(body.warnings) ? body.warnings.map(String) : [],
    normalized_char_count:
      typeof body.normalized_char_count === "number"
        ? body.normalized_char_count
        : 0,
    candidates: body.candidates.filter(
      (item): item is ChapterCandidate =>
        Boolean(item) && typeof item.candidate_id === "string",
    ),
  };
}

export async function loadDetection(
  sourceId: string,
  fetcher: typeof fetch = fetch,
): Promise<DetectionResult | { error: string }> {
  const response = await fetcher(`/api/imports/${sourceId}/detection`);
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    return { error: "章节检测失败，请返回重新导入。" };
  }
  return parseDetectionPayload(payload);
}

export function toDraft(result: DetectionResult): PreviewDraft {
  return {
    import_source_id: result.import_source_id,
    checksum: result.checksum,
    classification: result.classification,
    candidates: result.candidates,
    warnings: result.warnings,
    destination: "new_novel",
    novel_id: "",
    unstructured_ack: false,
    confirmed: false,
  };
}

export function readPreviewDraft(
  sourceId: string,
  storage: Pick<Storage, "getItem"> = window.sessionStorage,
): PreviewDraft | null {
  const raw = storage.getItem(previewStorageKey(sourceId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as PreviewDraft;
    if (parsed.import_source_id !== sourceId) return null;
    return {
      ...parsed,
      warnings: Array.isArray(parsed.warnings) ? parsed.warnings : [],
    };
  } catch {
    return null;
  }
}

export function writePreviewDraft(
  draft: PreviewDraft,
  storage: Pick<Storage, "setItem"> = window.sessionStorage,
): void {
  storage.setItem(
    previewStorageKey(draft.import_source_id),
    JSON.stringify(draft),
  );
}

export type ConfirmImportResult =
  | { ok: true; novel_id: string; chapter_id: string; idempotent: boolean }
  | { ok: false; message: string };

export async function confirmImport(
  draft: PreviewDraft,
  fetcher: typeof fetch = fetch,
): Promise<ConfirmImportResult> {
  const blocked = confirmBlockedReason(draft);
  if (blocked) return { ok: false, message: blocked };
  const response = await fetcher(
    `/api/imports/${draft.import_source_id}/confirm`,
    {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      checksum: draft.checksum,
      destination: draft.destination,
      novel_id: draft.destination === "append" ? draft.novel_id : null,
      unstructured_ack: draft.unstructured_ack,
      classification: draft.classification,
      candidates: draft.candidates,
    }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    return { ok: false, message: "确认失败，请检查章节范围后重试。" };
  }
  if (!payload || typeof payload !== "object") {
    return { ok: false, message: "确认失败，请检查章节范围后重试。" };
  }
  const body = payload as {
    novel_id?: string;
    idempotent?: boolean;
    chapters?: Array<{ chapter_id?: string }>;
  };
  const chapterId = body.chapters?.[0]?.chapter_id;
  if (typeof body.novel_id !== "string" || typeof chapterId !== "string") {
    return { ok: false, message: "确认失败，请检查章节范围后重试。" };
  }
  return {
    ok: true,
    novel_id: body.novel_id,
    chapter_id: chapterId,
    idempotent: body.idempotent === true,
  };
}
