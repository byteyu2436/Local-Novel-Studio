import { describe, expect, it } from "vitest";

import {
  chapterTree,
  consistencyView,
  draftDiff,
  latestPlan,
  moveScene,
  planEditorView,
  workspacePath,
  type PlanRecord,
} from "@/lib/writing";

const plan: PlanRecord = {
  id: "p2",
  version_number: 2,
  status: "confirmed",
  is_confirmed_pointer: true,
  model_ref: "qwen3.5:9b",
  plan: {
    chapter_goal: "林深离开雨巷",
    new_character_policy: "allow_if_necessary",
    scenes: [
      { scene_id: "leave", order: 2, goal: "离开" },
      { scene_id: "meet", order: 1, goal: "遇见鹿" },
    ],
  },
};

describe("writing workspace", () => {
  it("opens a workspace and treats the character policy as three choices", () => {
    expect(workspacePath("n1")).toBe("/novels/n1/workspace");
    const view = planEditorView(plan);
    expect(view.policy).toBe("allow_if_necessary");
    expect(view.policyLabel).toBe("必要时允许");
    expect(view.policyLabel).not.toBe("true");
    expect(view.scenes.map((scene) => scene.scene_id)).toEqual([
      "meet",
      "leave",
    ]);
    expect(view.canGenerate).toBe(true);
    expect(view.statusLabel).toBe("已确认");
    expect(view.model).toBe("qwen3.5:9b");
    expect(planEditorView(null).canGenerate).toBe(false);
  });

  it("reorders scenes, diffs a rewrite, and blocks accept on a blocking issue", () => {
    expect(moveScene(["meet", "leave"], "leave", -1)).toEqual([
      "leave",
      "meet",
    ]);
    expect(moveScene(["meet"], "meet", 1)).toEqual(["meet"]);
    const diff = draftDiff("甲乙丙", "甲丁丙");
    expect(diff.prefix).toBe("甲");
    expect(diff.removed).toBe("乙");
    expect(diff.added).toBe("丁");
    expect(diff.suffix).toBe("丙");
    const issues = consistencyView([
      { id: "w", severity: "warning", summary: "语气偏硬" },
      { id: "b", severity: "blocking", summary: "雨巷被改掉了" },
    ]);
    expect(issues.canAccept).toBe(false);
    expect(issues.blocking).toHaveLength(1);
    expect(
      consistencyView([{ id: "i", severity: "info", summary: "可以" }])
        .canAccept,
    ).toBe(true);
    expect(
      chapterTree([
        { chapter_id: "c2", sequence: 2, display_title: "二" },
        { chapter_id: "c1", sequence: 1, display_title: "一" },
      ]).map((item) => item.chapter_id),
    ).toEqual(["c1", "c2"]);
    expect(
      latestPlan([
        { ...plan, id: "p1", version_number: 1, status: "generated" },
        plan,
      ])?.id,
    ).toBe("p2");
  });
});
