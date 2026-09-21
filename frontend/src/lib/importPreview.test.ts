import { describe, expect, it, vi } from "vitest";

import {
  classificationLabel,
  confirmBlockedReason,
  confirmImport,
  mergeWithNext,
  moveCandidate,
  parseDetectionPayload,
  setSequence,
  splitAtRelativeOffset,
  toDraft,
  type ChapterCandidate,
} from "./importPreview";

const sample = (
  overrides: Partial<ChapterCandidate> = {},
): ChapterCandidate => ({
  candidate_id: "c1",
  sequence: 1,
  original_label: "第一章",
  title_candidate: "开场",
  start_offset: 0,
  end_offset: 10,
  confidence: 0.95,
  classification: "multi",
  preview_text: "第一章 开场",
  ...overrides,
});

describe("import preview edits", () => {
  it("merges, splits, and reorders candidates without dropping offsets", () => {
    const first = sample();
    const second = sample({
      candidate_id: "c2",
      sequence: 2,
      original_label: "第二章",
      start_offset: 10,
      end_offset: 20,
      preview_text: "第二章",
    });
    const merged = mergeWithNext([first, second], 0);
    expect(Array.isArray(merged)).toBe(true);
    if (Array.isArray(merged)) {
      expect(merged).toHaveLength(1);
      expect(merged[0].start_offset).toBe(0);
      expect(merged[0].end_offset).toBe(20);
    }

    const split = splitAtRelativeOffset([first], 0, 3);
    expect(Array.isArray(split)).toBe(true);
    if (Array.isArray(split)) {
      expect(split).toHaveLength(2);
      expect(split[0].end_offset).toBe(3);
      expect(split[1].start_offset).toBe(3);
    }

    const moved = moveCandidate([first, second], 1, -1);
    expect(Array.isArray(moved)).toBe(true);
    if (Array.isArray(moved)) {
      expect(moved[0].candidate_id).toBe("c2");
    }
    const numbered = setSequence([first], 0, 4);
    expect(Array.isArray(numbered) && numbered[0].sequence).toBe(4);
  });

  it("blocks unstructured confirm until acknowledged and keeps single destination rules", () => {
    expect(
      confirmBlockedReason({
        classification: "unstructured",
        destination: "new_novel",
        novel_id: "",
        unstructured_ack: false,
        candidates: [
          sample({ classification: "unstructured", confidence: 0.2 }),
        ],
      }),
    ).toBe("无明确结构的文本必须先确认切分建议。");
    expect(
      confirmBlockedReason({
        classification: "single",
        destination: "append",
        novel_id: "",
        unstructured_ack: true,
        candidates: [sample({ classification: "single" })],
      }),
    ).toBe("追加到已有小说时请填写小说 ID。");
    expect(
      confirmBlockedReason({
        classification: "single",
        destination: "new_novel",
        novel_id: "",
        unstructured_ack: false,
        candidates: [sample({ classification: "single" })],
      }),
    ).toBeNull();
    expect(classificationLabel("unstructured")).toContain("无明确");
  });

  it("parses detection payload for the preview page", () => {
    const parsed = parseDetectionPayload({
      import_source_id: "src-1",
      checksum: "abc",
      classification: "multi",
      warnings: ["preamble_attached_to_first_chapter"],
      normalized_char_count: 20,
      candidates: [sample()],
    });
    expect("error" in parsed).toBe(false);
    if (!("error" in parsed)) {
      const draft = toDraft(parsed);
      expect(draft.confirmed).toBe(false);
      expect(draft.destination).toBe("new_novel");
    }
  });

  it("posts confirm and returns a Reader chapter path payload", async () => {
    const draft = toDraft({
      import_source_id: "src-1",
      checksum: "abc",
      classification: "multi",
      warnings: [],
      normalized_char_count: 20,
      candidates: [sample(), sample({ candidate_id: "c2", sequence: 2 })],
    });
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        novel_id: "n1",
        idempotent: false,
        chapters: [{ chapter_id: "ch-1" }, { chapter_id: "ch-2" }],
      }),
    });
    const result = await confirmImport(draft, fetcher);
    expect(result).toEqual({
      ok: true,
      novel_id: "n1",
      chapter_id: "ch-1",
      idempotent: false,
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/imports/src-1/confirm",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
