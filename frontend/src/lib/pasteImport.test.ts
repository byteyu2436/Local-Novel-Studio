import { describe, expect, it, vi } from "vitest";

import {
  countPasteChars,
  importPreviewPath,
  importStatusLabel,
  parseImportErrorPayload,
  pasteClientError,
  submitButtonLabel,
  submitPastedText,
} from "./pasteImport";

describe("paste import form", () => {
  it("counts characters and rejects empty input without calling the API", async () => {
    expect(countPasteChars("第一章\n林深")).toBe(6);
    expect(pasteClientError("   \n")).toBe("请先粘贴小说正文。");
    const fetcher = vi.fn();
    const result = await submitPastedText("  ", fetcher);
    expect(fetcher).not.toHaveBeenCalled();
    expect(result).toEqual({
      ok: false,
      message: "请先粘贴小说正文。",
      text: "  ",
    });
  });

  it("keeps the original pasted text when the API returns an error", async () => {
    const pasted = "第一章\n很长的正文".repeat(20);
    const fetcher = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({
        detail: { code: "import_too_large", message: "too big" },
      }),
    });
    const result = await submitPastedText(pasted, fetcher);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.text).toBe(pasted);
      expect(result.message).toBe("正文太长，请分段后再导入。");
    }
    expect(
      parseImportErrorPayload({ detail: { code: "import_empty" } }, 400),
    ).toBe("请先粘贴小说正文。");
  });

  it("maps a successful paste to ImportSource and the chapter preview path", async () => {
    const pasted = "第一章 开场\n林深见鹿。";
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({
        id: "src-1",
        source_type: "paste",
        parse_status: "normalized",
        raw_char_count: 11,
        checksum: "should-not-surface-in-ui-helpers",
      }),
    });
    const result = await submitPastedText(pasted, fetcher);
    expect(result).toEqual({
      ok: true,
      text: pasted,
      source: {
        id: "src-1",
        source_type: "paste",
        parse_status: "normalized",
        raw_char_count: 11,
      },
    });
    expect(importPreviewPath("src-1")).toBe("/imports/src-1/preview");
    expect(submitButtonLabel("submitting")).toBe("正在导入…");
    expect(importStatusLabel("error")).toBe("导入失败");
  });
});
