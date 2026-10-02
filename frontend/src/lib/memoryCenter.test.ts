import { describe, expect, it } from "vitest";

import {
  MEMORY_TABS,
  factStatusLabel,
  factValueText,
  lockResult,
  memoryPath,
  memoryView,
  readerJumpPath,
  resolutionResult,
} from "./memoryCenter";

describe("memory center", () => {
  it("lists every memory tab and jumps back to the reader", () => {
    expect(MEMORY_TABS.map((tab) => tab.label)).toEqual([
      "人物",
      "关系",
      "事件",
      "时间线",
      "伏笔",
      "世界观",
      "文风",
    ]);
    expect(memoryPath("n1")).toBe("/novels/n1/memory");
    expect(readerJumpPath("n1", "c2", "v3")).toBe("/novels/n1/chapters/c2?version=v3");
    expect(readerJumpPath("n1", null, null)).toBeNull();
  });

  it("shows locked, superseded, empty, and error states", () => {
    expect(factValueText({ value: "18岁" })).toBe("18岁");
    expect(factStatusLabel({ status: "active", locked: true })).toBe("已锁定");
    expect(factStatusLabel({ status: "superseded", locked: false })).toBe("已取代");
    expect(memoryView({ loading: true, error: null, count: 0 }).state).toBe("loading");
    expect(memoryView({ loading: false, error: "失败", count: 0 })).toEqual({
      state: "error",
      message: "失败",
    });
    expect(memoryView({ loading: false, error: null, count: 0 }).state).toBe("empty");
  });

  it("does not pretend a failed lock or resolution succeeded", () => {
    expect(lockResult(false, false)).toEqual({
      locked: false,
      error: "锁定状态没有更新，请重试。",
    });
    expect(lockResult(false, true).locked).toBe(true);
    expect(resolutionResult(false, null)).toEqual({
      status: "open",
      error: "裁决没有保存，冲突仍待处理。",
    });
    expect(resolutionResult(true, "resolved").status).toBe("resolved");
  });
});
