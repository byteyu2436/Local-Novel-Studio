import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  countPasteChars,
  importPreviewPath,
  importStatusLabel,
  pasteClientError,
  submitButtonLabel,
  submitPastedText,
  type PasteSubmitState,
} from "@/lib/pasteImport";

export default function PasteImportPage() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [state, setState] = useState<PasteSubmitState>("idle");
  const [error, setError] = useState<string | null>(null);
  const chars = countPasteChars(text);
  const busy = state === "submitting";

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clientError = pasteClientError(text);
    if (clientError) {
      setState("error");
      setError(clientError);
      return;
    }
    setState("submitting");
    setError(null);
    try {
      const result = await submitPastedText(text);
      if (!result.ok) {
        setState("error");
        setError(result.message);
        setText(result.text);
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
        <h1 className="text-4xl font-semibold tracking-tight">粘贴正文</h1>
        <p className="max-w-2xl text-lg leading-7 text-muted-foreground">
          把单章或多章正文粘贴到下方。导入后会进入章节确认，不会立刻改写原文。
        </p>
      </div>

      <form className="flex flex-col gap-4" onSubmit={onSubmit}>
        <label className="flex flex-col gap-2">
          <span className="text-sm font-medium">小说正文</span>
          <textarea
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              if (state !== "submitting") {
                setState("idle");
                setError(null);
              }
            }}
            rows={18}
            placeholder="在这里粘贴章节正文…"
            className="min-h-[20rem] w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm leading-6 shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
            disabled={busy}
          />
        </label>
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
          <p>
            {chars} 字 · {importStatusLabel(state)}
          </p>
          {error ? <p className="text-destructive">{error}</p> : null}
        </div>
        <div className="flex flex-wrap gap-3">
          <Button type="submit" disabled={busy}>
            {submitButtonLabel(state)}
          </Button>
          <Button asChild variant="outline">
            <Link to="/">返回首页</Link>
          </Button>
        </div>
      </form>
    </main>
  );
}
