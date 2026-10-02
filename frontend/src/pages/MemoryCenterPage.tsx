import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  MEMORY_TABS,
  factStatusLabel,
  factValueText,
  lockResult,
  memoryView,
  readerJumpPath,
  resolutionResult,
  type AliasCandidate,
  type MemoryConflict,
  type MemoryFact,
  type MemoryKind,
} from "@/lib/memoryCenter";

type FactDetail = {
  fact: MemoryFact;
  provenance: { chapter_id: string | null; chapter_version_id: string | null };
  superseded_by_id: string | null;
  conflicts: MemoryConflict[];
};

export default function MemoryCenterPage() {
  const { novelId = "" } = useParams();
  const [kind, setKind] = useState<MemoryKind>("character");
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<FactDetail | null>(null);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<MemoryConflict[]>([]);
  const [aliases, setAliases] = useState<AliasCandidate[]>([]);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    const response = await fetch(`/api/novels/${novelId}/memory?kind=${kind}`);
    if (!response.ok) {
      setFacts([]);
      setError("记忆加载失败。");
      setLoading(false);
      return;
    }
    const body = (await response.json()) as { facts: MemoryFact[] };
    setFacts(body.facts);
    setLoading(false);
  }, [kind, novelId]);

  useEffect(() => {
    void reload();
    void fetch(`/api/novels/${novelId}/memory/conflicts`)
      .then((response) => (response.ok ? response.json() : { conflicts: [] }))
      .then((body: { conflicts: MemoryConflict[] }) => setConflicts(body.conflicts));
    void fetch(`/api/novels/${novelId}/memory/alias-candidates`)
      .then((response) => (response.ok ? response.json() : { candidates: [] }))
      .then((body: { candidates: AliasCandidate[] }) => setAliases(body.candidates));
  }, [novelId, reload]);

  async function openFact(factId: string) {
    setNotice(null);
    const response = await fetch(`/api/novels/${novelId}/memory/facts/${factId}`);
    if (!response.ok) {
      setNotice("事实详情加载失败。");
      return;
    }
    const detail = (await response.json()) as FactDetail;
    setSelected(detail);
    setDraft(factValueText(detail.fact.value));
  }

  async function toggleLock() {
    if (!selected) return;
    const action = selected.fact.locked ? "unlock" : "lock";
    const response = await fetch(
      `/api/novels/${novelId}/memory/facts/${selected.fact.id}/${action}`,
      { method: "POST" },
    );
    const next = lockResult(selected.fact.locked, response.ok);
    setNotice(next.error);
    if (next.error) return;
    await openFact(selected.fact.id);
    await reload();
  }

  async function saveEdit() {
    if (!selected) return;
    const response = await fetch(
      `/api/novels/${novelId}/memory/facts/${selected.fact.id}/edit`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          value: { value: draft },
          expected_revision: selected.fact.revision,
        }),
      },
    );
    if (!response.ok) {
      setNotice("编辑没有保存。事实修订可能已经变化。");
      return;
    }
    const body = (await response.json()) as { id: string; revision: number };
    setNotice(`已保存修订 ${body.revision}。`);
    await openFact(body.id);
    await reload();
  }

  async function resolve(conflictId: string, action: string, factValue?: { value: string }) {
    const response = await fetch(
      `/api/novels/${novelId}/memory/conflicts/${conflictId}/resolve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, fact_value: factValue ?? null }),
      },
    );
    const body = response.ok
      ? ((await response.json()) as { status: string })
      : null;
    const next = resolutionResult(response.ok, body?.status ?? null);
    setNotice(next.error ?? "冲突已更新。");
    if (next.error) return;
    await reload();
    if (selected) await openFact(selected.fact.id);
  }

  async function merge(candidate: AliasCandidate) {
    const [targetId, sourceId] = candidate.candidate_entity_ids;
    if (!targetId || !sourceId) {
      setNotice("这条候选没有足够明确的两个实体，不能合并。");
      return;
    }
    const response = await fetch(`/api/novels/${novelId}/memory/aliases/merge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
    });
    setNotice(response.ok ? "别名已合并。" : "合并没有完成。");
    if (response.ok) await reload();
  }

  const view = memoryView({ loading, error, count: facts.length });

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-4 px-6 py-8">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">记忆中心</h1>
        <Link className="text-sm underline" to={`/novels/${novelId}`}>
          返回阅读
        </Link>
      </div>
      <div className="flex flex-wrap gap-2">
        {MEMORY_TABS.map((tab) => (
          <Button
            key={tab.id}
            type="button"
            variant={tab.id === kind ? "default" : "ghost"}
            size="sm"
            onClick={() => setKind(tab.id)}
          >
            {tab.label}
          </Button>
        ))}
      </div>
      {view.state === "loading" ? <p>正在加载记忆…</p> : null}
      {view.state === "error" ? <p className="text-destructive">{view.message}</p> : null}
      {view.state === "empty" ? <p>这个分类里还没有事实。</p> : null}
      {view.state === "ready" ? (
        <ul className="flex flex-col gap-2">
          {facts.map((fact) => (
            <li key={fact.id}>
              <button
                type="button"
                className="w-full rounded-md border border-input px-3 py-2 text-left"
                onClick={() => void openFact(fact.id)}
              >
                <span className="font-medium">{fact.fact_key}</span>
                <span className="ml-2">{factValueText(fact.value)}</span>
                <span className="ml-2 text-xs">{factStatusLabel(fact)}</span>
                <span className="ml-2 text-xs">修订 {fact.revision}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {selected ? (
        <section className="rounded-md border border-input p-4">
          <h2 className="font-medium">
            {selected.fact.fact_key} · {factStatusLabel(selected.fact)}
          </h2>
          <p className="mt-2 text-sm">置信度 {selected.fact.confidence}</p>
          {readerJumpPath(
            novelId,
            selected.provenance.chapter_id,
            selected.provenance.chapter_version_id,
          ) ? (
            <Link
              className="text-sm underline"
              to={
                readerJumpPath(
                  novelId,
                  selected.provenance.chapter_id,
                  selected.provenance.chapter_version_id,
                ) ?? "/"
              }
            >
              查看来源章节
            </Link>
          ) : (
            <p className="text-sm">没有可跳转的来源章节。</p>
          )}
          <label className="mt-3 flex flex-col gap-1 text-sm">
            事实内容
            <input
              className="rounded-md border border-input px-2 py-1"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
          </label>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" size="sm" onClick={() => void saveEdit()}>
              保存编辑
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => void toggleLock()}>
              {selected.fact.locked ? "解锁" : "锁定"}
            </Button>
          </div>
          {selected.conflicts.map((conflict) => (
            <div key={conflict.id} className="mt-3 rounded-md bg-accent/40 p-3 text-sm">
              <p>
                冲突 {conflict.category}：现有 {factValueText(conflict.existing_value)} / 新值{" "}
                {factValueText(conflict.incoming_value)} · {conflict.status}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => void resolve(conflict.id, "keep_existing")}>
                  保留旧事实
                </Button>
                <Button type="button" size="sm" onClick={() => void resolve(conflict.id, "accept_incoming")}>
                  采用新事实
                </Button>
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void resolve(conflict.id, "edit", { value: draft })}
                >
                  手工编辑
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => void resolve(conflict.id, "dismiss")}>
                  标记误判
                </Button>
              </div>
            </div>
          ))}
        </section>
      ) : null}
      {conflicts.length > 0 ? (
        <p className="text-sm">待处理冲突 {conflicts.length} 条。</p>
      ) : null}
      {aliases.length > 0 ? (
        <section>
          <h2 className="font-medium">别名候选</h2>
          <ul className="mt-2 flex flex-col gap-2">
            {aliases.map((candidate) => (
              <li key={candidate.id} className="text-sm">
                {candidate.mention_name} · {candidate.reason}
                <Button className="ml-2" type="button" size="sm" onClick={() => void merge(candidate)}>
                  确认合并
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {notice ? <p className="text-sm">{notice}</p> : null}
    </main>
  );
}
