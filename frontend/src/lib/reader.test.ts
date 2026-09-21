import { describe, expect, it, vi } from "vitest";

import {
  loadNovelChapters,
  parseTocPayload,
  readerPath,
  resolveActiveChapter,
  tocItemLabel,
} from "./reader";

const SAMPLE = {
  novel_id: "n1",
  novel_title: "十八章样例",
  chapters: Array.from({ length: 18 }, (_, index) => ({
    chapter_id: `c${index + 1}`,
    sequence: index + 1,
    original_label: index === 4 ? "" : `第${index + 1}章`,
    display_title: index === 4 ? "第5章" : `第${index + 1}章 标题`,
    title_source: index === 4 ? "fallback" : "original",
    canon_kind: "ORIGINAL",
    has_draft: false,
  })),
};

describe("reader shell", () => {
  it("keeps novel/chapter location in the URL for refresh", () => {
    expect(readerPath("n1")).toBe("/novels/n1");
    expect(readerPath("n1", "c3")).toBe("/novels/n1/chapters/c3");
    const parsed = parseTocPayload(SAMPLE);
    if ("error" in parsed) throw new Error(parsed.error);
    expect(resolveActiveChapter(parsed, "c12")?.chapter_id).toBe("c12");
    expect(resolveActiveChapter(parsed, undefined)?.chapter_id).toBe("c1");
    expect(resolveActiveChapter(parsed, "missing")?.chapter_id).toBe("c1");
    expect(parsed.chapters).toHaveLength(18);
    expect(tocItemLabel(parsed.chapters[4])).toBe("第5章");
  });

  it("surfaces a clear error when the TOC API fails", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: { code: "novel_not_found" } }),
    });
    const result = await loadNovelChapters("missing", fetcher);
    expect(result).toEqual({ error: "章节目录加载失败，请确认小说是否存在。" });
    expect(parseTocPayload(null)).toEqual({ error: "无法读取章节目录。" });
  });
});
