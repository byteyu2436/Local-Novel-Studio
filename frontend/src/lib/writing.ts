export type PlanScene = {
  scene_id: string;
  order: number;
  goal: string;
};

export type PlanRecord = {
  id: string;
  version_number: number;
  status: string;
  is_confirmed_pointer: boolean;
  model_ref: string;
  plan: {
    chapter_goal: string;
    new_character_policy: "forbid" | "allow" | "allow_if_necessary";
    scenes: PlanScene[];
  };
};

export type ConsistencyIssue = {
  id: string;
  severity: "info" | "warning" | "blocking";
  summary: string;
};

export type TocChapter = {
  chapter_id: string;
  sequence: number;
  display_title: string;
};

const POLICY_LABEL = {
  forbid: "禁止新角色",
  allow: "允许新角色",
  allow_if_necessary: "必要时允许",
} as const;

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  generated: "已生成",
  edited: "已修改",
  confirmed: "已确认",
  superseded: "已替换",
};

export function workspacePath(novelId: string): string {
  return `/novels/${novelId}/workspace`;
}

export function planEditorView(plan: PlanRecord | null) {
  if (!plan) {
    return {
      goal: "",
      policy: "forbid" as const,
      policyLabel: POLICY_LABEL.forbid,
      scenes: [] as PlanScene[],
      statusLabel: "还没有计划",
      version: 0,
      model: "",
      canGenerate: false,
    };
  }
  const policy = plan.plan.new_character_policy;
  return {
    goal: plan.plan.chapter_goal,
    policy,
    policyLabel: POLICY_LABEL[policy],
    scenes: [...plan.plan.scenes].sort(
      (left, right) => left.order - right.order,
    ),
    statusLabel: STATUS_LABEL[plan.status] ?? plan.status,
    version: plan.version_number,
    model: plan.model_ref,
    canGenerate: plan.status === "confirmed" && plan.is_confirmed_pointer,
  };
}

export function moveScene(
  ids: string[],
  sceneId: string,
  direction: -1 | 1,
): string[] {
  const next = [...ids];
  const index = next.indexOf(sceneId);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= next.length) return next;
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item);
  return next;
}

export function draftDiff(before: string, after: string) {
  let start = 0;
  while (
    start < before.length &&
    start < after.length &&
    before[start] === after[start]
  ) {
    start += 1;
  }
  let endBefore = before.length;
  let endAfter = after.length;
  while (
    endBefore > start &&
    endAfter > start &&
    before[endBefore - 1] === after[endAfter - 1]
  ) {
    endBefore -= 1;
    endAfter -= 1;
  }
  return {
    prefix: before.slice(0, start),
    removed: before.slice(start, endBefore),
    added: after.slice(start, endAfter),
    suffix: before.slice(endBefore),
  };
}

export function consistencyView(issues: ConsistencyIssue[]) {
  const blocking = issues.filter((item) => item.severity === "blocking");
  return {
    blocking,
    warnings: issues.filter((item) => item.severity === "warning"),
    canAccept: blocking.length === 0,
  };
}

export function chapterTree(chapters: TocChapter[]): TocChapter[] {
  return [...chapters].sort((left, right) => left.sequence - right.sequence);
}

export function latestPlan(plans: PlanRecord[]): PlanRecord | null {
  return (
    [...plans].sort(
      (left, right) => right.version_number - left.version_number,
    )[0] ?? null
  );
}
