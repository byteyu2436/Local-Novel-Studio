import {
  importPreviewPath,
  parseImportErrorPayload,
  parsePasteImportResponse,
  type PasteImportResult,
} from "@/lib/pasteImport";

export type TxtSubmitState =
  "idle" | "previewing" | "ready" | "importing" | "success" | "error";

export type TxtFileLike = {
  name: string;
  size: number;
};

export type TxtEncodingChoice = "" | "utf-8" | "gbk" | "gb18030";

export type TxtPreview = {
  original_filename: string;
  raw_byte_size: number;
  detected_encoding: string | null;
  encoding_uncertain: boolean;
  preview_text: string;
  preview_truncated: boolean;
  char_count: number;
};

export type TxtPreviewResult =
  { ok: true; preview: TxtPreview } | { ok: false; message: string };

export const TXT_MAX_BYTES = 8_000_000;

export const TXT_ENCODING_OPTIONS: {
  value: TxtEncodingChoice;
  label: string;
}[] = [
  { value: "", label: "自动检测" },
  { value: "utf-8", label: "UTF-8" },
  { value: "gbk", label: "GBK" },
  { value: "gb18030", label: "GB18030" },
];

const ERROR_COPY: Record<string, string> = {
  txt_filename_required: "请先选择 TXT 文件。",
  txt_unsupported_type: "目前只支持 TXT 文件，暂不支持该格式。",
  txt_empty: "TXT 文件是空的。",
  txt_binary: "这个文件看起来不是小说正文，请选择 TXT。",
  txt_too_large: "文件太大，请选择不超过 8 MB 的 TXT。",
  txt_decode_failed: "无法识别编码，请手动选择 UTF-8 或 GBK 后重新预览。",
  txt_encoding_invalid: "按所选编码无法正确解码，请换一种编码后重新预览。",
  txt_encoding_unsupported: "不支持该编码，请选择 UTF-8、GBK 或 GB18030。",
  txt_persist_failed: "原文保存失败，请重新选择文件后再试。",
};

export function txtClientError(file: TxtFileLike | null): string | null {
  if (file == null) return ERROR_COPY.txt_filename_required;
  const name = file.name.trim();
  if (!name.toLowerCase().endsWith(".txt")) {
    return ERROR_COPY.txt_unsupported_type;
  }
  if (file.size === 0) return ERROR_COPY.txt_empty;
  if (file.size > TXT_MAX_BYTES) return ERROR_COPY.txt_too_large;
  return null;
}

export function formatTxtBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function encodingLabel(encoding: string | null): string {
  if (encoding === "utf-8") return "UTF-8";
  if (encoding === "gbk") return "GBK";
  if (encoding === "gb18030") return "GB18030";
  return "未检测";
}

export function showEncodingOverride(uncertain: boolean): boolean {
  return uncertain;
}

export function txtStatusLabel(state: TxtSubmitState): string {
  if (state === "previewing") return "正在预览";
  if (state === "ready") return "预览就绪";
  if (state === "importing") return "正在保存原文";
  if (state === "success") return "导入成功";
  if (state === "error") return "导入失败";
  return "等待选择文件";
}

export function previewButtonLabel(state: TxtSubmitState): string {
  if (state === "previewing") return "正在预览…";
  return "重新预览";
}

export function importButtonLabel(state: TxtSubmitState): string {
  if (state === "importing") return "正在导入…";
  return "确认导入";
}

export function parseTxtErrorPayload(
  payload: unknown,
  httpStatus: number,
): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      const code = String((detail as { code: unknown }).code);
      if (code in ERROR_COPY) return ERROR_COPY[code];
    }
  }
  return parseImportErrorPayload(payload, httpStatus);
}

export function parseTxtPreviewResponse(payload: unknown): TxtPreviewResult {
  if (!payload || typeof payload !== "object") {
    return { ok: false, message: "预览失败，请重新选择文件。" };
  }
  const body = payload as Partial<TxtPreview>;
  if (typeof body.preview_text !== "string") {
    return { ok: false, message: "预览失败，请重新选择文件。" };
  }
  return {
    ok: true,
    preview: {
      original_filename:
        typeof body.original_filename === "string"
          ? body.original_filename
          : "novel.txt",
      raw_byte_size:
        typeof body.raw_byte_size === "number" ? body.raw_byte_size : 0,
      detected_encoding:
        typeof body.detected_encoding === "string"
          ? body.detected_encoding
          : null,
      encoding_uncertain: Boolean(body.encoding_uncertain),
      preview_text: body.preview_text,
      preview_truncated: Boolean(body.preview_truncated),
      char_count: typeof body.char_count === "number" ? body.char_count : 0,
    },
  };
}

function appendTxtForm(file: File, encoding: TxtEncodingChoice): FormData {
  const body = new FormData();
  body.append("file", file);
  if (encoding) body.append("encoding", encoding);
  return body;
}

export async function previewTxtFile(
  file: File,
  encoding: TxtEncodingChoice = "",
  fetcher: typeof fetch = fetch,
): Promise<TxtPreviewResult> {
  const clientError = txtClientError(file);
  if (clientError) return { ok: false, message: clientError };
  const response = await fetcher("/api/imports/txt/preview", {
    method: "POST",
    body: appendTxtForm(file, encoding),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    return {
      ok: false,
      message: parseTxtErrorPayload(payload, response.status),
    };
  }
  return parseTxtPreviewResponse(payload);
}

export async function importTxtFile(
  file: File,
  encoding: TxtEncodingChoice = "",
  fetcher: typeof fetch = fetch,
): Promise<PasteImportResult> {
  const clientError = txtClientError(file);
  if (clientError) return { ok: false, message: clientError, text: "" };
  const response = await fetcher("/api/imports/txt", {
    method: "POST",
    body: appendTxtForm(file, encoding),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    return {
      ok: false,
      message: parseTxtErrorPayload(payload, response.status),
      text: "",
    };
  }
  return parsePasteImportResponse(payload, "");
}

export { importPreviewPath };
