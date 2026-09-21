import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  encodingLabel,
  formatTxtBytes,
  importButtonLabel,
  importPreviewPath,
  importTxtFile,
  previewButtonLabel,
  previewTxtFile,
  txtClientError,
  txtStatusLabel,
  TXT_ENCODING_OPTIONS,
  type TxtEncodingChoice,
  type TxtPreview,
  type TxtSubmitState,
} from "@/lib/txtImport";

export default function TxtImportPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [encoding, setEncoding] = useState<TxtEncodingChoice>("");
  const [preview, setPreview] = useState<TxtPreview | null>(null);
  const [state, setState] = useState<TxtSubmitState>("idle");
  const [error, setError] = useState<string | null>(null);
  const busy = state === "previewing" || state === "importing";
  const fileReady = file != null && txtClientError(file) == null;

  async function runPreview(nextFile: File, nextEncoding: TxtEncodingChoice) {
    setState("previewing");
    setError(null);
    try {
      const result = await previewTxtFile(nextFile, nextEncoding);
      if (!result.ok) {
        setState("error");
        setError(result.message);
        setPreview(null);
        return;
      }
      setPreview(result.preview);
      setState("ready");
    } catch {
      setState("error");
      setError("导入服务暂时不可用，请稍后重试。");
      setPreview(null);
    }
  }

  async function onPickFile(event: ChangeEvent<HTMLInputElement>) {
    const next = event.target.files?.[0] ?? null;
    setFile(next);
    setPreview(null);
    setEncoding("");
    if (state !== "previewing" && state !== "importing") {
      setState("idle");
      setError(null);
    }
    if (next == null) return;
    const clientError = txtClientError(next);
    if (clientError) {
      setState("error");
      setError(clientError);
      return;
    }
    await runPreview(next, "");
  }

  async function onChangeEncoding(event: ChangeEvent<HTMLSelectElement>) {
    const next = event.target.value as TxtEncodingChoice;
    setEncoding(next);
    if (file == null) return;
    await runPreview(file, next);
  }

  async function onRePreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (file == null) {
      setState("error");
      setError(txtClientError(null));
      return;
    }
    const clientError = txtClientError(file);
    if (clientError) {
      setState("error");
      setError(clientError);
      return;
    }
    await runPreview(file, encoding);
  }

  async function onImport() {
    if (file == null) {
      setState("error");
      setError(txtClientError(null));
      return;
    }
    setState("importing");
    setError(null);
    try {
      const result = await importTxtFile(file, encoding);
      if (!result.ok) {
        setState("error");
        setError(result.message);
        return;
      }
      setState("success");
      navigate(importPreviewPath(result.source.id));
    } catch {
      setState("error");
      setError("导入服务暂时不可用，请稍后重试。");
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 px-6 py-16">
      <div className="space-y-3">
        <p className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
          导入小说
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">上传 TXT</h1>
        <p className="max-w-2xl text-lg leading-7 text-muted-foreground">
          选择 TXT
          文件，先预览解码结果，再进入与粘贴导入相同的章节确认。暂不支持
          DOCX、EPUB 或 Markdown。
        </p>
      </div>

      <form className="flex flex-col gap-4" onSubmit={onRePreview}>
        <label className="flex flex-col gap-2">
          <span className="text-sm font-medium">TXT 文件</span>
          <input
            type="file"
            accept=".txt,text/plain"
            onChange={onPickFile}
            disabled={busy}
            className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground"
          />
        </label>

        {file ? (
          <p className="text-sm text-muted-foreground">
            {file.name} · {formatTxtBytes(file.size)}
            {preview
              ? ` · 检测编码 ${encodingLabel(preview.detected_encoding)}`
              : ""}
          </p>
        ) : null}

        {fileReady ? (
          <label className="flex max-w-xs flex-col gap-2">
            <span className="text-sm font-medium">编码</span>
            <select
              value={encoding}
              onChange={onChangeEncoding}
              disabled={busy}
              className="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {TXT_ENCODING_OPTIONS.map((option) => (
                <option key={option.value || "auto"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {preview?.encoding_uncertain ? (
              <span className="text-sm text-muted-foreground">
                编码可能不准确，请对照预览后选择正确编码。
              </span>
            ) : (
              <span className="text-sm text-muted-foreground">
                如果预览乱码，请改选编码后重新预览。
              </span>
            )}
          </label>
        ) : null}

        {preview ? (
          <label className="flex flex-col gap-2">
            <span className="text-sm font-medium">正文预览</span>
            <textarea
              readOnly
              value={preview.preview_text}
              rows={14}
              className="min-h-[16rem] w-full resize-y rounded-md border border-input bg-muted/40 px-3 py-2 text-sm leading-6 shadow-sm"
            />
            <span className="text-sm text-muted-foreground">
              {preview.char_count} 字
              {preview.preview_truncated ? " · 仅显示开头预览" : ""} ·{" "}
              {txtStatusLabel(state)}
            </span>
          </label>
        ) : (
          <p className="text-sm text-muted-foreground">
            {txtStatusLabel(state)}
          </p>
        )}

        {error ? <p className="text-sm text-destructive">{error}</p> : null}

        <div className="flex flex-wrap gap-3">
          <Button
            type="submit"
            variant="outline"
            disabled={busy || file == null}
          >
            {previewButtonLabel(state)}
          </Button>
          <Button
            type="button"
            onClick={onImport}
            disabled={busy || preview == null}
          >
            {importButtonLabel(state)}
          </Button>
          <Button asChild variant="outline">
            <Link to="/import">改用粘贴导入</Link>
          </Button>
          <Button asChild variant="ghost">
            <Link to="/">返回首页</Link>
          </Button>
        </div>
      </form>
    </main>
  );
}
