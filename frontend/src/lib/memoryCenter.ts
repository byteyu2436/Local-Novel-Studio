export const MEMORY_TABS = [
  { id: "character", label: "人物" },
  { id: "relationship", label: "关系" },
  { id: "event", label: "事件" },
  { id: "timeline", label: "时间线" },
  { id: "foreshadowing", label: "伏笔" },
  { id: "world_fact", label: "世界观" },
  { id: "style_profile", label: "文风" },
] as const;

export type MemoryKind = (typeof MEMORY_TABS)[number]["id"];

export type MemoryFact = {
  id: string;
  fact_key: string;
  value: { value?: string };
  confidence: number;
  locked: boolean;
  status: string;
  revision: number;
  source_chapter_id: string | null;
  source_chapter_version_id: string | null;
  source_chapter_title: string;
};

export type MemoryConflict = {
  id: string;
  category: string;
  fact_key: string;
  status: string;
  existing_fact_id: string;
  existing_value: { value?: string };
  incoming_value: { value?: string };
  existing_source_chapter_id: string | null;
  incoming_source_chapter_id: string | null;
};

export type AliasCandidate = {
  id: string;
  mention_name: string;
  reason: string;
  candidate_entity_ids: string[];
  source_chapter_id: string;
};

export function memoryPath(novelId: string): string {
  return `/novels/${novelId}/memory`;
}

export function readerJumpPath(
  novelId: string,
  chapterId: string | null,
  versionId: string | null,
): string | null {
  if (!chapterId) return null;
  const base = `/novels/${novelId}/chapters/${chapterId}`;
  if (!versionId) return base;
  return `${base}?version=${encodeURIComponent(versionId)}`;
}

export function factValueText(value: { value?: unknown }): string {
  if (value && "value" in value && value.value != null) return String(value.value);
  return "";
}

export function factStatusLabel(fact: Pick<MemoryFact, "status" | "locked">): string {
  if (fact.locked) return "已锁定";
  if (fact.status === "superseded") return "已取代";
  if (fact.status === "active") return "当前";
  return fact.status;
}

export type MemoryView =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "empty" }
  | { state: "ready" };

export function memoryView(input: {
  loading: boolean;
  error: string | null;
  count: number;
}): MemoryView {
  if (input.loading) return { state: "loading" };
  if (input.error) return { state: "error", message: input.error };
  if (input.count === 0) return { state: "empty" };
  return { state: "ready" };
}

export function lockResult(locked: boolean, responseOk: boolean): {
  locked: boolean;
  error: string | null;
} {
  if (!responseOk) return { locked, error: "锁定状态没有更新，请重试。" };
  return { locked: !locked, error: null };
}

export function resolutionResult(
  responseOk: boolean,
  status: string | null,
): { status: string | null; error: string | null } {
  if (!responseOk || !status) {
    return { status: "open", error: "裁决没有保存，冲突仍待处理。" };
  }
  return { status, error: null };
}
