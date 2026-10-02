import { describe, expect, it } from "vitest";

import {
  candidateReaderPath,
  debugPath,
  debugView,
  dedupLabel,
  scoreRows,
  type DebugCandidate,
} from "@/lib/retrievalDebug";

const candidate: DebugCandidate = {
  chunk_id: "c1",
  chapter_id: "ch1",
  source_version_id: "v1",
  dense_score: 0.4,
  business_score: 0.2,
  final_score: 0.6,
  match_reasons: ["character"],
  score_breakdown: { dense: 0.4, character: 1 },
  status: "rejected",
  reason: "adjacent_overlap",
  kept_chunk_id: "c0",
  excerpt: "雨巷",
};

describe("retrieval debug view", () => {
  it("keeps debug out of the author route", () => {
    expect(debugPath("n1")).toBe("/dev/novels/n1/retrieval");
    expect(debugPath("n1").startsWith("/novels/")).toBe(false);
  });

  it("maps loading, error, and empty states", () => {
    expect(debugView({ loading: true, error: null, result: null }).state).toBe(
      "loading",
    );
    expect(
      debugView({ loading: false, error: "失败", result: null }).state,
    ).toBe("error");
    expect(
      debugView({
        loading: false,
        error: null,
        result: { novel_id: "n1", evidence: [] },
      }).state,
    ).toBe("empty");
  });

  it("explains score breakdown, dedup, and the reader jump", () => {
    expect(scoreRows(candidate).map((row) => row.name)).toEqual([
      "dense",
      "character",
    ]);
    expect(dedupLabel(candidate)).toContain("c0");
    expect(candidateReaderPath("n1", candidate)).toBe(
      "/novels/n1/chapters/ch1?version=v1",
    );
  });
});
