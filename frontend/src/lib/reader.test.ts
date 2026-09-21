import { describe, expect, it, vi } from "vitest";

import {
  canonKindLabel,
  loadCanonChapter,
  loadChapterVersion,
  loadNovelChapters,
  navDisabled,
  parseTocPayload,
  readerPath,
  readingChapterPath,
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
    expect(readerPath("n1", "c3", "v9")).toBe("/novels/n1/chapters/c3?version=v9");
    expect(readingChapterPath("n1", "c3")).toBe("/novels/n1/chapters/c3");
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

  it("loads Canon body, keeps Draft preview separate, and bounds navigation", async () => {
    const chapters = Array.from({ length: 18 }, (_, index) => `c${index + 1}`);
    const first = {
      novel_id: "n1",
      chapter_id: "c1",
      sequence: 1,
      original_label: "第一章",
      original_title: "",
      display_title: "第一章",
      title_source: "original",
      body: "第一章正文",
      version_id: "v-canon",
      version_kind: "ORIGINAL",
      is_canon: true,
      has_draft: true,
      previous: null,
      next: { chapter_id: "c2", sequence: 2, display_title: "第二章" },
    };
    const fetcher = vi.fn(async (url: string) => {
      if (url.endsWith("/versions/v-draft")) {
        return {
          ok: true,
          json: async () => ({
            body: "草稿正文",
            version_id: "v-draft",
            version_kind: "DRAFT",
            is_canon: false,
          }),
        };
      }
      return { ok: true, json: async () => first };
    });
    const canon = await loadCanonChapter("c1", fetcher as unknown as typeof fetch);
    if ("error" in canon) throw new Error(canon.error);
    expect(canon.body).toBe("第一章正文");
    expect(canonKindLabel(canon.version_kind, canon.is_canon)).toBe("原文 Canon");
    expect(navDisabled("previous", canon)).toBe(true);
    expect(navDisabled("next", canon)).toBe(false);
    const preview = await loadChapterVersion(
      "c1",
      "v-draft",
      fetcher as unknown as typeof fetch,
    );
    if ("error" in preview) throw new Error(preview.error);
    expect(preview.body).toBe("草稿正文");
    expect(preview.is_canon).toBe(false);
    expect(canonKindLabel(preview.version_kind, preview.is_canon)).toBe(
      "草稿预览，不是当前 Canon",
    );
    expect(chapters).toHaveLength(18);
  });
});
