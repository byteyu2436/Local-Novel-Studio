import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  chapterTree,
  consistencyView,
  draftDiff,
  latestPlan,
  moveScene,
  planEditorView,
  type ConsistencyIssue,
  type PlanRecord,
  type TocChapter,
} from "@/lib/writing";

type DraftRecord = { id: string; body: string; parent_id: string | null };

export default function WritingWorkspacePage() {
  const { novelId = "" } = useParams();
  const [chapters, setChapters] = useState<TocChapter[]>([]);
  const [plans, setPlans] = useState<PlanRecord[]>([]);
  const [goal, setGoal] = useState("下一章");
  const [policy, setPolicy] =
    useState<PlanRecord["plan"]["new_character_policy"]>("forbid");
  const [draft, setDraft] = useState<DraftRecord | null>(null);
  const [previousBody, setPreviousBody] = useState("");
  const [instruction, setInstruction] = useState("改得更克制");
  const [issues, setIssues] = useState<ConsistencyIssue[]>([]);
  const [message, setMessage] = useState("");
  const current = latestPlan(plans);
  const editor = planEditorView(current);
  const review = consistencyView(issues);
  const diff = draft ? draftDiff(previousBody, draft.body) : null;

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [chapterResponse, planResponse] = await Promise.all([
        fetch(`/api/novels/${novelId}/chapters`),
        fetch(`/api/novels/${novelId}/plans`),
      ]);
      if (cancelled) return;
      if (chapterResponse.ok) {
        const body = (await chapterResponse.json()) as {
          chapters: TocChapter[];
        };
        setChapters(chapterTree(body.chapters ?? []));
      }
      if (planResponse.ok) {
        const body = (await planResponse.json()) as { plans: PlanRecord[] };
        const next = body.plans ?? [];
        setPlans(next);
        const newest = latestPlan(next);
        if (newest) {
          setGoal(newest.plan.chapter_goal);
          setPolicy(newest.plan.new_character_policy);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [novelId]);

  async function reloadPlans() {
    const response = await fetch(`/api/novels/${novelId}/plans`);
    if (!response.ok) {
      setMessage("计划没有加载出来。");
      return;
    }
    const body = (await response.json()) as { plans: PlanRecord[] };
    setPlans(body.plans ?? []);
  }

  async function generatePlan() {
    const sequence = chapters.length + 1;
    const response = await fetch(`/api/novels/${novelId}/plans`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chapter_goal: goal, target_sequence: sequence }),
    });
    if (!response.ok) {
      setMessage("计划没有生成。");
      return;
    }
    await reloadPlans();
    setMessage("计划已生成，确认后才能写正文。");
  }

  async function saveEdits() {
    if (!current) return;
    const response = await fetch(
      `/api/novels/${novelId}/plans/${current.id}/edit`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...current.plan,
          chapter_goal: goal,
          new_character_policy: policy,
        }),
      },
    );
    if (!response.ok) {
      setMessage("这版计划没有保存。");
      return;
    }
    await reloadPlans();
    setMessage("已保存为新版本。");
  }

  async function reorder(sceneId: string, direction: -1 | 1) {
    if (!current) return;
    const sceneIds = moveScene(
      editor.scenes.map((scene) => scene.scene_id),
      sceneId,
      direction,
    );
    const response = await fetch(
      `/api/novels/${novelId}/plans/${current.id}/reorder`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scene_ids: sceneIds }),
      },
    );
    if (!response.ok) {
      setMessage("场景顺序没有改成。");
      return;
    }
    await reloadPlans();
  }

  async function confirm() {
    if (!current) return;
    const response = await fetch(
      `/api/novels/${novelId}/plans/${current.id}/confirm`,
      {
        method: "POST",
      },
    );
    if (!response.ok) {
      setMessage("这版计划不能确认。");
      return;
    }
    await reloadPlans();
    setMessage("计划已确认，可以生成正文。");
  }

  async function generateScene(sceneId: string) {
    if (!current) return;
    const response = await fetch(`/api/novels/${novelId}/scenes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: current.id, scene_id: sceneId }),
    });
    if (!response.ok) {
      setMessage("正文没有写出来。");
      return;
    }
    const body = (await response.json()) as {
      text: string;
      draft: { id: string } | null;
    };
    if (body.draft)
      setDraft({ id: body.draft.id, body: body.text, parent_id: null });
    setMessage(editor.canGenerate ? "场景已生成。" : "还不能生成。");
  }

  async function saveDraft() {
    if (!draft) return;
    const response = await fetch(`/api/novels/${novelId}/drafts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_sequence: chapters.length + 1,
        body: draft.body,
        plan_id: current?.id ?? null,
      }),
    });
    if (!response.ok) {
      setMessage("草稿没有保存。");
      return;
    }
    const saved = (await response.json()) as DraftRecord;
    setPreviousBody(draft.body);
    setDraft(saved);
    setMessage("草稿已保存为新版本。");
  }

  async function rewriteDraft() {
    if (!draft || !draft.body) return;
    const response = await fetch(
      `/api/novels/${novelId}/drafts/${draft.id}/rewrite`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start: 0,
          end: draft.body.length,
          instruction,
        }),
      },
    );
    if (!response.ok) {
      setMessage("改写没有完成。");
      return;
    }
    const saved = (await response.json()) as DraftRecord;
    setPreviousBody(draft.body);
    setDraft(saved);
    setMessage("已生成改写版本，前后文保持原样。");
  }

  async function restoreDraft() {
    if (!draft) return;
    const response = await fetch(
      `/api/novels/${novelId}/drafts/${draft.id}/restore`,
      { method: "POST" },
    );
    if (!response.ok) {
      setMessage("这一版没有恢复。");
      return;
    }
    const saved = (await response.json()) as DraftRecord;
    setPreviousBody(draft.body);
    setDraft(saved);
    setMessage("已按这一版恢复成新版本。");
  }

  async function checkConsistency() {
    if (!draft) return;
    const response = await fetch(
      `/api/novels/${novelId}/drafts/${draft.id}/consistency`,
      {
        method: "POST",
      },
    );
    if (!response.ok) {
      setMessage("一致性检查没有完成。");
      return;
    }
    const body = (await response.json()) as { issues: ConsistencyIssue[] };
    setIssues(body.issues ?? []);
  }

  async function acceptDraft() {
    if (!draft || !current || !review.canAccept) return;
    const response = await fetch(
      `/api/novels/${novelId}/drafts/${draft.id}/accept`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan_id: current.id }),
      },
    );
    if (!response.ok) {
      setMessage("这版草稿还不能接受。");
      return;
    }
    const chapterResponse = await fetch(`/api/novels/${novelId}/chapters`);
    if (chapterResponse.ok) {
      const body = (await chapterResponse.json()) as { chapters: TocChapter[] };
      setChapters(chapterTree(body.chapters ?? []));
    }
    setMessage("已接受为正文。");
  }

  return (
    <main className="mx-auto grid min-h-screen max-w-6xl gap-6 px-6 py-8 lg:grid-cols-[16rem_1fr_18rem]">
      <section className="flex flex-col gap-3">
        <h1 className="text-xl font-semibold">章节</h1>
        <ol className="flex flex-col gap-2">
          {chapterTree(chapters).map((chapter) => (
            <li key={chapter.chapter_id}>
              <Link to={`/novels/${novelId}/chapters/${chapter.chapter_id}`}>
                {chapter.sequence}. {chapter.display_title}
              </Link>
            </li>
          ))}
        </ol>
        {chapters.length === 0 ? <p>还没有已接受的章节。</p> : null}
      </section>
      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">这一章</h2>
        <label className="flex flex-col gap-2">
          章节目标
          <textarea
            className="min-h-24 rounded-md border border-input px-3 py-2"
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
          />
        </label>
        <label className="flex flex-col gap-2">
          新角色
          <select
            className="rounded-md border border-input px-3 py-2"
            value={policy}
            onChange={(event) =>
              setPolicy(
                event.target
                  .value as PlanRecord["plan"]["new_character_policy"],
              )
            }
          >
            <option value="forbid">禁止新角色</option>
            <option value="allow">允许新角色</option>
            <option value="allow_if_necessary">必要时允许</option>
          </select>
        </label>
        <div className="flex flex-wrap gap-2">
          <Button type="button" onClick={() => void generatePlan()}>
            生成计划
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => void saveEdits()}
          >
            保存修改
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => void confirm()}
          >
            确认计划
          </Button>
        </div>
        <p>
          {editor.statusLabel} · 第 {editor.version} 版 · {editor.policyLabel}
          {editor.model ? ` · ${editor.model}` : ""}
        </p>
        <p>{editor.canGenerate ? "可以生成正文" : "确认计划后才能生成正文"}</p>
        <ol className="flex flex-col gap-2">
          {editor.scenes.map((scene) => (
            <li
              key={scene.scene_id}
              className="rounded-md border border-input px-3 py-2"
            >
              <p>
                {scene.order}. {scene.goal}
              </p>
              <div className="mt-2 flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void reorder(scene.scene_id, -1)}
                >
                  上移
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void reorder(scene.scene_id, 1)}
                >
                  下移
                </Button>
                <Button
                  type="button"
                  disabled={!editor.canGenerate}
                  onClick={() => void generateScene(scene.scene_id)}
                >
                  生成这一场
                </Button>
              </div>
            </li>
          ))}
        </ol>
        <h2 className="text-xl font-semibold">草稿</h2>
        <textarea
          className="min-h-32 rounded-md border border-input px-3 py-2"
          value={draft?.body ?? ""}
          onChange={(event) =>
            setDraft((currentDraft) =>
              currentDraft
                ? { ...currentDraft, body: event.target.value }
                : currentDraft,
            )
          }
        />
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => void saveDraft()}
          >
            保存草稿
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => void rewriteDraft()}
          >
            局部改写
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={() => void restoreDraft()}
          >
            恢复这一版
          </Button>
        </div>
        <label className="flex flex-col gap-2">
          改写要求
          <input
            className="rounded-md border border-input px-3 py-2"
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
          />
        </label>
        {diff && (diff.removed || diff.added) ? (
          <p>
            改动：{diff.removed || "（空）"} → {diff.added || "（空）"}
          </p>
        ) : null}
        {message ? <p>{message}</p> : null}
      </section>
      <section className="flex flex-col gap-3">
        <h2 className="text-xl font-semibold">检查</h2>
        <Button
          type="button"
          variant="outline"
          onClick={() => void checkConsistency()}
        >
          检查一致性
        </Button>
        <ul className="flex flex-col gap-2">
          {issues.map((issue) => (
            <li key={issue.id}>
              {issue.severity === "blocking"
                ? "挡住"
                : issue.severity === "warning"
                  ? "提醒"
                  : "提示"}
              ：{issue.summary}
            </li>
          ))}
        </ul>
        <Button
          type="button"
          disabled={!review.canAccept || !draft}
          onClick={() => void acceptDraft()}
        >
          接受为正文
        </Button>
        <Link to={`/novels/${novelId}`}>回到阅读</Link>
      </section>
    </main>
  );
}
