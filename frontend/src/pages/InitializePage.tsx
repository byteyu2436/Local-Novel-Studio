import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  initView,
  visiblePhases,
  writingPath,
  type InitializationStatus,
} from "@/lib/initialization";

export default function InitializePage() {
  const { novelId = "" } = useParams();
  const [status, setStatus] = useState<InitializationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const view = initView(status, loading, error);

  const reload = useCallback(async () => {
    const response = await fetch(`/api/novels/${novelId}/initialization`);
    if (!response.ok) {
      setError("初始化状态加载失败。");
      setLoading(false);
      return;
    }
    setStatus((await response.json()) as InitializationStatus);
    setError(null);
    setLoading(false);
  }, [novelId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const response = await fetch(`/api/novels/${novelId}/initialization`);
      if (cancelled) return;
      if (!response.ok) {
        setError("初始化状态加载失败。");
        setLoading(false);
        return;
      }
      setStatus((await response.json()) as InitializationStatus);
      setError(null);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [novelId]);

  async function act(
    action: "initialize" | "pause" | "resume" | "cancel" | "retry",
  ) {
    const path =
      action === "initialize"
        ? `/api/novels/${novelId}/initialize`
        : `/api/novels/${novelId}/initialization/${action}`;
    const response = await fetch(path, { method: "POST" });
    if (!response.ok) {
      setError("操作没有完成。");
      return;
    }
    setStatus((await response.json()) as InitializationStatus);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-10">
      <p className="text-sm text-muted-foreground">准备续写</p>
      <h1 className="text-3xl font-semibold">{view.headline}</h1>
      {status ? (
        <ol className="flex flex-col gap-2">
          {visiblePhases(status.phases).map((phase) => (
            <li
              key={phase.label}
              className="rounded-md border border-input px-3 py-2"
            >
              <span className="font-medium">{phase.label}</span>
              <span className="ml-3 text-sm text-muted-foreground">
                {phase.status}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
      {status?.error_message ? (
        <p className="text-sm text-destructive">{status.error_message}</p>
      ) : null}
      {status?.suggested_action ? (
        <p className="text-sm text-muted-foreground">
          {status.suggested_action}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {view.canStart ? (
          <Button type="button" onClick={() => void act("initialize")}>
            开始初始化
          </Button>
        ) : null}
        {status?.state === "running" ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => void act("pause")}
          >
            暂停
          </Button>
        ) : null}
        {view.canResume ? (
          <Button
            type="button"
            onClick={() =>
              void act(status?.state === "failed" ? "retry" : "resume")
            }
          >
            {status?.state === "failed" ? "重试" : "继续"}
          </Button>
        ) : null}
        {status &&
        status.state !== "completed" &&
        status.state !== "not_started" ? (
          <Button
            type="button"
            variant="ghost"
            onClick={() => void act("cancel")}
          >
            取消
          </Button>
        ) : null}
        <Button asChild variant="outline">
          <Link to={writingPath(novelId)}>查看续写入口</Link>
        </Button>
        <Button type="button" variant="ghost" onClick={() => void reload()}>
          刷新
        </Button>
      </div>
    </main>
  );
}
