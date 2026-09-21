import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  overallLabel,
  statusClassName,
  type CheckStatus,
} from "@/lib/diagnostics";

type DiagnosticCheck = {
  id: string;
  label: string;
  status: CheckStatus;
  summary: string;
  hint: string | null;
};

type DiagnosticsResponse = {
  generated_at: string;
  overall_status: CheckStatus;
  checks: DiagnosticCheck[];
  copy_summary: string;
};

export default function DiagnosticsPage() {
  const [data, setData] = useState<DiagnosticsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    fetch("/api/system/diagnostics", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Diagnostics HTTP ${response.status}`);
        }
        setData((await response.json()) as DiagnosticsResponse);
        setError(null);
        setCopied(false);
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(
          "无法读取诊断接口。请先运行 scripts/dev-backend.ps1，然后刷新。",
        );
      });

    return () => controller.abort();
  }, [refreshNonce]);

  async function copySummary() {
    if (!data) return;
    await navigator.clipboard.writeText(data.copy_summary);
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
          本地运行诊断。摘要不含小说正文；GPU 探测失败不会阻止应用启动。
        </p>
      </div>

      <div className="flex flex-wrap gap-3">
        <Button asChild variant="outline">
          <Link to="/">返回首页</Link>
        </Button>
        <Button
          type="button"
          onClick={() => setRefreshNonce((value) => value + 1)}
        >
          刷新诊断
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => void copySummary()}
          disabled={!data}
        >
          {copied ? "已复制摘要" : "复制诊断摘要"}
        </Button>
      </div>

      {error && (
        <section className="rounded-xl border border-red-200 bg-red-50 p-6 text-red-900">
          {error}
        </section>
      )}

      {data && (
        <section className="space-y-4">
          <div
            className={`rounded-xl border p-6 ${statusClassName(data.overall_status)}`}
          >
            <p className="text-sm font-medium">总体状态</p>
            <p className="mt-1 text-2xl font-semibold">
              {overallLabel(data.overall_status)}
            </p>
          </div>
          {data.checks.map((check) => (
            <article
              key={check.id}
              className={`rounded-xl border p-5 ${statusClassName(check.status)}`}
            >
              <div className="flex items-baseline justify-between gap-3">
                <h2 className="text-base font-medium">{check.label}</h2>
                <span className="text-sm">{overallLabel(check.status)}</span>
              </div>
              <p className="mt-2 text-sm">{check.summary}</p>
              {check.hint && (
                <p className="mt-2 text-sm opacity-80">建议：{check.hint}</p>
              )}
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
