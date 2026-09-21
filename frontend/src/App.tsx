import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

type HealthState = "checking" | "ok" | "unavailable";

export default function App() {
  const [health, setHealth] = useState<HealthState>("checking");

  useEffect(() => {
    const controller = new AbortController();

    fetch("/health", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          setHealth("unavailable");
          return;
        }
        const payload = (await response.json()) as { status?: string };
        setHealth(payload.status === "ok" ? "ok" : "unavailable");
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setHealth("unavailable");
        }
      });

    return () => controller.abort();
  }, []);

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-8 px-6 py-16">
      <div className="space-y-3">
        <p className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
          v0.1.0 Foundation
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">
          Local Novel Studio
        </h1>
        <p className="max-w-2xl text-lg leading-7 text-muted-foreground">
          开源、本地优先的长篇小说续写工具。当前已建立可独立启动的前后端骨架；导入、分析与续写会在后续版本接入。
        </p>
      </div>

      <section className="rounded-xl border bg-card p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-medium">本地 API</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {health === "checking" && "正在检查 /health …"}
              {health === "ok" && "后端已启动，/health 返回 ok。"}
              {health === "unavailable" &&
                "后端暂不可达。请先运行 scripts/dev-backend.ps1。"}
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => window.location.reload()}
            type="button"
          >
            刷新状态
          </Button>
        </div>
      </section>
    </main>
  );
}
