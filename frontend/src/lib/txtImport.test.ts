import { describe, expect, it, vi } from "vitest";

import {
  encodingLabel,
  formatTxtBytes,
  importButtonLabel,
  importPreviewPath,
  importTxtFile,
  parseTxtErrorPayload,
  previewButtonLabel,
  previewTxtFile,
  showEncodingOverride,
  txtClientError,
  txtStatusLabel,
} from "./txtImport";

function fakeFile(name: string, size: number): File {
  const bytes = new Uint8Array(Math.min(size, 8));
  const file = new File([bytes], name, { type: "text/plain" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("txt import helpers", () => {
  it("rejects missing, empty, oversized, and non-txt files before calling the API", async () => {
    expect(txtClientError(null)).toBe("请先选择 TXT 文件。");
    expect(txtClientError({ name: "notes.md", size: 12 })).toBe(
      "目前只支持 TXT 文件，暂不支持该格式。",
    );
    expect(txtClientError({ name: "empty.txt", size: 0 })).toBe(
      "TXT 文件是空的。",
    );
    expect(txtClientError({ name: "huge.txt", size: 8_000_001 })).toBe(
      "文件太大，请选择不超过 8 MB 的 TXT。",
    );
    const fetcher = vi.fn();
    const skipped = await previewTxtFile(
      fakeFile("notes.docx", 20),
      "",
      fetcher,
    );
    expect(fetcher).not.toHaveBeenCalled();
    expect(skipped.ok).toBe(false);
    if (!skipped.ok) {
      expect(skipped.message).toBe("目前只支持 TXT 文件，暂不支持该格式。");
    }
  });

  it("maps preview payload and keeps encoding override in the request body", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        original_filename: "novel.txt",
        raw_byte_size: 24,
        detected_encoding: "gbk",
        encoding_uncertain: false,
        preview_text: "第一章 开场",
        preview_truncated: false,
        char_count: 6,
      }),
    });
    const result = await previewTxtFile(
      fakeFile("novel.txt", 24),
      "gbk",
      fetcher,
    );
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.preview.detected_encoding).toBe("gbk");
      expect(result.preview.preview_text).toContain("第一章");
    }
    const body = fetcher.mock.calls[0][1].body as FormData;
    expect(body.get("encoding")).toBe("gbk");
    expect(showEncodingOverride(true)).toBe(true);
    expect(showEncodingOverride(false)).toBe(false);
    expect(encodingLabel("gbk")).toBe("GBK");
    expect(formatTxtBytes(1536)).toBe("1.5 KB");
  });

  it("imports through the same chapter-preview path as paste", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: async () => ({
        id: "src-txt",
        source_type: "txt",
        parse_status: "normalized",
        raw_char_count: 6,
      }),
    });
    const result = await importTxtFile(fakeFile("novel.txt", 12), "", fetcher);
    expect(result).toEqual({
      ok: true,
      text: "",
      source: {
        id: "src-txt",
        source_type: "txt",
        parse_status: "normalized",
        raw_char_count: 6,
      },
    });
    expect(importPreviewPath("src-txt")).toBe("/imports/src-txt/preview");
    expect(
      parseTxtErrorPayload(
        { detail: { code: "txt_decode_failed", message: "x" } },
        400,
      ),
    ).toBe("无法识别编码，请手动选择 UTF-8 或 GBK 后重新预览。");
    expect(txtStatusLabel("ready")).toBe("预览就绪");
    expect(previewButtonLabel("previewing")).toBe("正在预览…");
    expect(importButtonLabel("importing")).toBe("正在导入…");
  });
});
