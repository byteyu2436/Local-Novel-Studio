import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  candidateReaderPath,
  debugView,
  dedupLabel,
  scoreRows,
  type RetrievalDebugResponse,
} from "@/lib/retrievalDebug";

export default function RetrievalDebugPage() {
  const { novelId = "" } = useParams();
  const [goal, setGoal] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RetrievalDebugResponse | null>(null);
  const view = debugView({ loading, error, result });

  async function run() {
    setLoading(true);
    setError(null);
    const response = await fetch(
      `/api/novels/${novelId}/retrieval?debug=true`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chapter_goal: goal }),
      },
    );
    if (!response.ok) {
      setResult(null);
      setError("检索失败。");
      setLoading(false);
      return;
    }
    setResult((await response.json()) as RetrievalDebugResponse);
    setLoading(false);
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-6 px-6 py-10">
      <p className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
        开发诊断
      </p>
      <h1 className="text-3xl font-semibold">检索追踪</h1>
      <label className="flex flex-col gap-2 text-sm">
        章节目标
        <textarea
          className="min-h-24 rounded-md border border-input px-3 py-2"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
        />
      </label>
      <Button type="button" onClick={() => void run()}>
        运行检索
      </Button>
      <p className="text-sm">{view.message}</p>
      {result?.trace ? (
        <section className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            {result.trace.query_builder_version} ·{" "}
            {result.trace.scoring_profile_version} ·{" "}
            {result.trace.selection_version}
          </p>
          <p className="break-all text-xs text-muted-foreground">
            {result.trace.filter_expr}
          </p>
          <ol className="flex flex-col gap-3">
            {result.trace.candidates.map((candidate) => (
              <li
                key={candidate.chunk_id}
                className="rounded-md border border-input p-3"
              >
                <div className="flex items-center justify-between gap-3">
                  <Link to={candidateReaderPath(novelId, candidate)}>
                    {candidate.excerpt}
                  </Link>
                  <span className="text-sm">{candidate.status}</span>
                </div>
                <p className="text-sm text-muted-foreground">
                  {dedupLabel(candidate)}
                </p>
                <ul className="text-xs text-muted-foreground">
                  {scoreRows(candidate).map((row) => (
                    <li key={row.name}>
                      {row.name}: {row.value}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </main>
  );
}
