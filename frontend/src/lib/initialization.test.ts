import { describe, expect, it } from "vitest";

import {
  initView,
  initializePath,
  visiblePhases,
  writingPath,
  writingView,
  type InitializationStatus,
} from "@/lib/initialization";

const running: InitializationStatus = {
  run_id: "r1",
  novel_id: "n1",
  state: "running",
  current_phase: "embedding",
  phase_label: "准备检索索引",
  phases: [
    {
      id: "analysis",
      label: "分析章节",
      detail: "分析章节",
      status: "completed",
    },
    {
      id: "memory_reduce",
      label: "构建记忆",
      detail: "构建记忆",
      status: "completed",
    },
    {
      id: "chunk",
      label: "准备检索索引",
      detail: "整理章节",
      status: "completed",
    },
    {
      id: "embedding",
      label: "准备检索索引",
      detail: "准备检索",
      status: "running",
    },
    {
      id: "index_validate_activate",
      label: "准备检索索引",
      detail: "校验索引",
      status: "pending",
    },
    { id: "ready", label: "完成", detail: "完成", status: "pending" },
  ],
  progress_done: 3,
  progress_total: 6,
  error_code: null,
  error_message: null,
  suggested_action: null,
  ready: false,
};

describe("initialization view", () => {
  it("uses author routes and keeps an unfinished novel closed", () => {
    expect(initializePath("n1")).toBe("/novels/n1/initialize");
    expect(writingPath("n1")).toBe("/novels/n1/write");
    expect(
      writingView({
        ready: false,
        state: "running",
        message: "初始化尚未完成，还不能续写。",
      }).ready,
    ).toBe(false);
    expect(
      writingView({
        ready: false,
        state: "failed",
        message: "初始化失败，还不能续写。",
      }).message,
    ).toContain("不能续写");
  });

  it("collapses index stages into one author label", () => {
    const labels = visiblePhases(running.phases).map((phase) => phase.label);
    expect(labels).toEqual(["分析章节", "构建记忆", "准备检索索引", "完成"]);
    expect(initView(running, false, null).headline).toBe("准备检索索引");
    expect(initView(null, false, null).canStart).toBe(true);
    expect(
      initView({ ...running, state: "paused" }, false, null).canResume,
    ).toBe(true);
  });
});
