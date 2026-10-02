import { readerPath } from "@/lib/reader";

export type DebugCandidate = {
  chunk_id: string;
  chapter_id: string;
  source_version_id: string;
  dense_score: number | null;
  business_score: number | null;
  final_score: number | null;
  match_reasons: string[];
  score_breakdown: Record<string, number>;
  status: "selected" | "rejected" | "filtered";
  reason: string | null;
  kept_chunk_id: string | null;
  excerpt: string;
};

export type RetrievalDebugTrace = {
  query: { semantic_text?: string; novel_id?: string };
  filter_expr: string;
  query_builder_version: string;
  scoring_profile_version: string;
  selection_version: string;
  embedding_profile_id: string | null;
  index_version: string | null;
  collection_name: string | null;
  stages: Record<string, string>;
  candidates: DebugCandidate[];
  final_evidence_ids: string[];
};

export type RetrievalDebugResponse = {
  novel_id: string;
  evidence: { chunk_id: string; final_score: number | null }[];
  trace?: RetrievalDebugTrace;
  empty?: boolean;
};

export function debugView(input: {
  loading: boolean;
  error: string | null;
  result: RetrievalDebugResponse | null;
}) {
  if (input.loading) return { state: "loading" as const, message: "正在检索…" };
  if (input.error) return { state: "error" as const, message: input.error };
  if (!input.result || input.result.evidence.length === 0) {
    return { state: "empty" as const, message: "没有可用证据。" };
  }
  return {
    state: "ready" as const,
    message: `命中 ${input.result.evidence.length} 条`,
  };
}

export function scoreRows(candidate: DebugCandidate) {
  return Object.entries(candidate.score_breakdown).map(([name, value]) => ({
    name,
    value,
  }));
}

export function dedupLabel(candidate: DebugCandidate): string | null {
  if (candidate.status === "selected") return null;
  if (
    candidate.reason === "overlap" ||
    candidate.reason === "adjacent_overlap"
  ) {
    return `与 ${candidate.kept_chunk_id ?? "已选片段"} 重叠，已去掉`;
  }
  if (candidate.reason === "duplicate_checksum") return "正文相同，已去掉";
  if (candidate.status === "filtered") return candidate.reason ?? "已过滤";
  return candidate.reason;
}

export function candidateReaderPath(
  novelId: string,
  candidate: DebugCandidate,
): string {
  return readerPath(novelId, candidate.chapter_id, candidate.source_version_id);
}

export function debugPath(novelId: string): string {
  return `/dev/novels/${novelId}/retrieval`;
}
