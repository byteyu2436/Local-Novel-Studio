export type PasteSubmitState = "idle" | "submitting" | "success" | "error";

export type PasteImportSource = {
  id: string;
  source_type: "paste" | "txt";
  parse_status: "received" | "normalized" | "failed";
  raw_char_count: number;
};

export type PasteImportResult =
  | { ok: true; source: PasteImportSource; text: string }
  | { ok: false; message: string; text: string };

const ERROR_COPY: Record<string, string> = {
  import_empty: "请先粘贴小说正文。",
  import_too_large: "正文太长，请分段后再导入。",
  import_invalid_characters: "正文包含无法导入的字符，请检查后重试。",
};

export function countPasteChars(text: string): number {
  return [...text].length;
}

export function pasteClientError(text: string): string | null {
  if (text.trim().length === 0) return ERROR_COPY.import_empty;
  return null;
}

export function submitButtonLabel(state: PasteSubmitState): string {
  if (state === "submitting") return "正在导入…";
  return "导入正文";
}

export function importStatusLabel(state: PasteSubmitState): string {
  if (state === "submitting") return "正在保存原文";
  if (state === "success") return "导入成功";
  if (state === "error") return "导入失败";
  return "等待粘贴";
}

export function parseImportErrorPayload(
  payload: unknown,
  httpStatus: number,
): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (detail && typeof detail === "object" && "code" in detail) {
      const code = String((detail as { code: unknown }).code);
      if (code in ERROR_COPY) return ERROR_COPY[code];
      if (
        "message" in detail &&
        typeof (detail as { message: unknown }).message === "string"
      ) {
        return (detail as { message: string }).message;
      }
    }
  }
  if (httpStatus >= 500) return "导入服务暂时不可用，请稍后重试。";
  return "导入失败，请检查正文后重试。";
}

export function parsePasteImportResponse(
  payload: unknown,
  text: string,
): PasteImportResult {
  if (!payload || typeof payload !== "object") {
    return { ok: false, message: "导入失败，请检查正文后重试。", text };
  }
  const body = payload as Partial<PasteImportSource>;
  if (typeof body.id !== "string" || body.id.length === 0) {
    return { ok: false, message: "导入失败，请检查正文后重试。", text };
  }
  return {
    ok: true,
    text,
    source: {
      id: body.id,
      source_type: body.source_type === "txt" ? "txt" : "paste",
      parse_status:
        body.parse_status === "failed" || body.parse_status === "received"
          ? body.parse_status
          : "normalized",
      raw_char_count:
        typeof body.raw_char_count === "number"
          ? body.raw_char_count
          : countPasteChars(text),
    },
  };
}

export async function submitPastedText(
  text: string,
  fetcher: typeof fetch = fetch,
): Promise<PasteImportResult> {
  const clientError = pasteClientError(text);
  if (clientError) return { ok: false, message: clientError, text };
  const response = await fetcher("/api/imports/paste", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    return {
      ok: false,
      message: parseImportErrorPayload(payload, response.status),
      text,
    };
  }
  return parsePasteImportResponse(payload, text);
}

export function importPreviewPath(sourceId: string): string {
  return `/imports/${sourceId}/preview`;
}
