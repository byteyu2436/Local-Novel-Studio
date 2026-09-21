import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  classificationLabel,
  confirmBlockedReason,
  confirmImport,
  isLowConfidence,
  loadDetection,
  mergeWithNext,
  moveCandidate,
  readPreviewDraft,
  setSequence,
  splitAtRelativeOffset,
  toDraft,
  writePreviewDraft,
  type PreviewDestination,
  type PreviewDraft,
} from "@/lib/importPreview";
import { readingChapterPath } from "@/lib/reader";

export default function ImportPreviewPage() {
  const { sourceId = "" } = useParams();
  const [draft, setDraft] = useState<PreviewDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [splitAt, setSplitAt] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      const result = await loadDetection(sourceId);
      if (cancelled) return;
      if ("error" in result) {
        setError(result.error);
        setDraft(null);
        setLoading(false);
        return;
      }
      const existing = readPreviewDraft(sourceId);
      setDraft(
        existing && existing.checksum === result.checksum
          ? existing
          : toDraft(result),
      );
      setError(null);
      setLoading(false);
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [sourceId]);

  function update(next: PreviewDraft) {
    setDraft(next);
    writePreviewDraft({ ...next, confirmed: false });
    setError(null);
  }

  function applyCandidates(
    outcome: PreviewDraft["candidates"] | { error: string },
  ) {
    if (!draft) return;
    if ("error" in outcome) {
      setError(outcome.error);
      return;
    }
    update({ ...draft, candidates: outcome, confirmed: false });
  }

  async function onConfirm() {
    if (!draft) return;
    const blocked = confirmBlockedReason(draft);
    if (blocked) {
      setError(blocked);
      return;
    }
    setConfirming(true);
    const result = await confirmImport(draft);
    setConfirming(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    const confirmed = {
      ...draft,
      confirmed: true,
      confirmedNovelId: result.novel_id,
      confirmedChapterId: result.chapter_id,
      novel_id: result.novel_id,
    };
    setDraft(confirmed);
    writePreviewDraft(confirmed);
  }

  const blocked = draft ? confirmBlockedReason(draft) : "正在读取检测结果";

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 px-6 py-16">
      <div className="space-y-3">
        <p className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
          导入小说
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">确认章节</h1>
        <p className="max-w-2xl text-lg leading-7 text-muted-foreground">
          先检查检测结果，再合并、拆分或调整顺序。确认前不会创建正式章节，也不会改写原文。
        </p>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">正在识别章节…</p>
      ) : null}
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {draft ? (
        <section className="flex flex-col gap-5">
          <p className="rounded-md border border-input px-3 py-2 text-sm">
            当前结构：{classificationLabel(draft.classification)}
            {draft.warnings.length ? ` · ${draft.warnings.join("，")}` : ""}
          </p>

          {draft.classification === "single" ? (
            <fieldset className="flex flex-col gap-2 text-sm">
              <legend className="font-medium">导入方式</legend>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name="destination"
                  checked={draft.destination === "new_novel"}
                  onChange={() =>
                    update({ ...draft, destination: "new_novel" })
                  }
                />
                作为新小说第一章
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="radio"
                  name="destination"
                  checked={draft.destination === "append"}
                  onChange={() =>
                    update({
                      ...draft,
                      destination: "append" as PreviewDestination,
                    })
                  }
                />
                追加到已有小说
              </label>
              {draft.destination === "append" ? (
                <input
                  value={draft.novel_id}
                  onChange={(event) =>
                    update({ ...draft, novel_id: event.target.value })
                  }
                  placeholder="已有小说 ID"
                  className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                />
              ) : null}
            </fieldset>
          ) : null}

          {draft.classification === "unstructured" ? (
            <label className="flex items-start gap-2 rounded-md border border-dashed px-3 py-2 text-sm">
              <input
                type="checkbox"
                checked={draft.unstructured_ack}
                onChange={(event) =>
                  update({ ...draft, unstructured_ack: event.target.checked })
                }
              />
              <span>
                这是切分建议，不是自动章节。我已检查范围，确认可以继续。
              </span>
            </label>
          ) : null}

          <ol className="flex flex-col gap-4">
            {draft.candidates.map((candidate, index) => (
              <li
                key={candidate.candidate_id}
                className="flex flex-col gap-3 rounded-md border border-input p-4"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <label className="text-sm font-medium">
                    序号
                    <input
                      type="number"
                      min={1}
                      value={candidate.sequence}
                      onChange={(event) =>
                        applyCandidates(
                          setSequence(
                            draft.candidates,
                            index,
                            Number(event.target.value),
                          ),
                        )
                      }
                      className="ml-2 h-8 w-20 rounded-md border border-input px-2 text-sm"
                    />
                  </label>
                  <p className="text-sm">
                    {candidate.original_label || "无原始标题"}
                    {candidate.title_candidate
                      ? ` · ${candidate.title_candidate}`
                      : ""}
                  </p>
                  {isLowConfidence(candidate) ? (
                    <span className="text-xs text-destructive">低置信度</span>
                  ) : null}
                </div>
                <p className="whitespace-pre-wrap text-sm leading-6 text-muted-foreground">
                  {candidate.preview_text}
                </p>
                <p className="text-xs text-muted-foreground">
                  offset {candidate.start_offset}–{candidate.end_offset}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      applyCandidates(
                        moveCandidate(draft.candidates, index, -1),
                      )
                    }
                  >
                    上移
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      applyCandidates(moveCandidate(draft.candidates, index, 1))
                    }
                  >
                    下移
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      applyCandidates(mergeWithNext(draft.candidates, index))
                    }
                  >
                    与下一章合并
                  </Button>
                  <label className="flex items-center gap-2 text-sm">
                    拆分位置
                    <input
                      value={splitAt[candidate.candidate_id] ?? ""}
                      onChange={(event) =>
                        setSplitAt((current) => ({
                          ...current,
                          [candidate.candidate_id]: event.target.value,
                        }))
                      }
                      className="h-8 w-20 rounded-md border border-input px-2"
                    />
                  </label>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      applyCandidates(
                        splitAtRelativeOffset(
                          draft.candidates,
                          index,
                          Number(splitAt[candidate.candidate_id] || 0),
                        ),
                      )
                    }
                  >
                    拆分
                  </Button>
                </div>
              </li>
            ))}
          </ol>

          {draft.confirmed && draft.confirmedNovelId && draft.confirmedChapterId ? (
            <p className="text-sm font-medium">
              正式章节已创建。
              <Link
                className="ml-2 underline"
                to={readingChapterPath(
                  draft.confirmedNovelId,
                  draft.confirmedChapterId,
                )}
              >
                打开 Reader
              </Link>
            </p>
          ) : null}

          <div className="flex flex-wrap gap-3">
            <Button
              type="button"
              onClick={() => void onConfirm()}
              disabled={Boolean(blocked) || confirming || draft.confirmed}
            >
              {confirming ? "正在创建章节…" : "确认并创建章节"}
            </Button>
            <Button asChild variant="outline">
              <Link to="/import">返回粘贴导入</Link>
            </Button>
            <Button asChild variant="ghost">
              <Link to="/import/txt">返回 TXT 导入</Link>
            </Button>
          </div>
        </section>
      ) : null}
    </main>
  );
}
