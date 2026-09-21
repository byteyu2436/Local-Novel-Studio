import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  checkExtraLabel,
  diagnosticsView,
  overallLabel,
  statusClassName,
  type DiagnosticsResponse,
} from "@/lib/diagnostics";

export default function DiagnosticsPage() {
  const [previous, setPrevious] = useState<DiagnosticsResponse | null>(null);
  const [incoming, setIncoming] = useState<
    | { type: "loading" }
    | { type: "error" }
    | { type: "ok"; payload: unknown }
  >({ type: "loading" });
  const [copied, setCopied] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const view = useMemo(
    () => diagnosticsView({ previous, incoming }),
    [previous, incoming],
  );

  useEffect(() => {
    const controller = new AbortController();

    fetch("/api/system/diagnostics", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Diagnostics HTTP ${response.status}`);
        }
        const payload: unknown = await response.json();
        setIncoming({ type: "ok", payload });
        if (
          payload &&
          typeof payload === "object" &&
          "copy_summary" in payload
        ) {
          setPrevious(payload as DiagnosticsResponse);
        }
        setCopied(false);
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setIncoming({ type: "error" });
      });

    return () => controller.abort();
  }, [refreshNonce]);

  async function copySummary() {
    if (!view.data) return;
    await navigator.clipboard.writeText(view.data.copy_summary);
    setCopied(true);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 px-6 py-16">
      <div className="space-y-3">
        <p className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
          v0.1.0 Foundation
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">系统健康</h1>
        <p className="max-w-2xl text-lg leading-7 text-muted-foreground">
          本地运行诊断。展示 Python / Node、SQLite、数据目录、Ollama、Milvus、RAM
          与 GPU。摘要不含小说正文；GPU 探测失败不会阻止其它检查。
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <Button asChild variant="outline">
          <Link to="/">返回首页</Link>
        </Button>
        <Button
          type="button"
          onClick={() => {
            setIncoming({ type: "loading" });
            setRefreshNonce((value) => value + 1);
          }}
        >
          刷新诊断
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => void copySummary()}
          disabled={!view.data}
        >
          {copied ? "已复制摘要" : "复制诊断摘要"}
        </Button>
      </div>

      {view.phase === "loading" && (
        <section className="rounded-xl border border-slate-200 bg-slate-50 p-6 text-slate-800">
          正在读取诊断…
        </section>
      )}

      {view.error && (
        <section className="rounded-xl border border-red-200 bg-red-50 p-6 text-red-900">
          {view.error}
        </section>
      )}

      {view.data && (
        <section className="space-y-4">
          <div
            className={`rounded-xl border p-6 ${statusClassName(view.data.overall_status)}`}
          >
            <p className="text-sm font-medium">总体状态</p>
            <p className="mt-1 text-2xl font-semibold">
              {overallLabel(view.data.overall_status)}
            </p>
          </div>
          {view.checks.map((check) => {
            const extra = checkExtraLabel(check);
            return (
              <article
                key={check.id}
                className={`rounded-xl border p-5 ${statusClassName(check.status)}`}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <h2 className="text-base font-medium">{check.label}</h2>
                  <span className="text-sm">
                    {overallLabel(check.status)}
                  </span>
                </div>
                {extra && <p className="mt-1 text-sm opacity-80">{extra}</p>}
                <p className="mt-2 text-sm">{check.summary}</p>
                {check.hint && (
                  <p className="mt-2 text-sm opacity-80">建议：{check.hint}</p>
                )}
              </article>
            );
          })}
        </section>
      )}
    </main>
  );
}
