import { describe, expect, it } from "vitest";

import {
  checkExtraLabel,
  diagnosticsView,
  gpuPresenceFromCode,
  gpuPresenceLabel,
  overallLabel,
  statusClassName,
  summaryLooksPrivate,
} from "./diagnostics";

describe("diagnostics status rendering", () => {
  it("maps statuses to Chinese labels", () => {
    expect(overallLabel("ok")).toBe("正常");
    expect(overallLabel("warning")).toBe("警告");
    expect(overallLabel("error")).toBe("异常");
  });

  it("uses distinct classes for ok/warning/error", () => {
    expect(statusClassName("ok")).toContain("emerald");
    expect(statusClassName("warning")).toContain("amber");
    expect(statusClassName("error")).toContain("red");
  });

  it("does not treat novel body as part of a diagnostics summary", () => {
    const summary = "sqlite: ok — app.db @ 0001_app_settings";
    expect(summaryLooksPrivate(summary, "THE SECRET NOVEL BODY")).toBe(true);
  });

  it("distinguishes no GPU from a probe failure", () => {
    expect(gpuPresenceFromCode("gpu_absent")).toBe("absent");
    expect(gpuPresenceFromCode("gpu_probe_failed")).toBe("probe_failed");
    expect(gpuPresenceLabel("absent")).toBe("无 NVIDIA GPU");
    expect(gpuPresenceLabel("probe_failed")).toBe("GPU 探测失败");
  });

  it("keeps loading, error, and partial payloads renderable", () => {
    const loading = diagnosticsView({
      previous: null,
      incoming: { type: "loading" },
    });
    expect(loading.phase).toBe("loading");
    expect(loading.checks).toEqual([]);

    const failed = diagnosticsView({
      previous: null,
      incoming: { type: "error" },
    });
    expect(failed.phase).toBe("error");
    expect(failed.error).toMatch(/dev-backend/);

    const partial = diagnosticsView({
      previous: null,
      incoming: {
        type: "ok",
        payload: {
          generated_at: "2026-09-21T00:00:00Z",
          overall_status: "warning",
          copy_summary: "partial",
          checks: [
            {
              id: "python",
              label: "Python",
              status: "ok",
              summary: "Python 3.12",
              hint: null,
            },
            {
              id: "gpu",
              label: "GPU",
              status: "warning",
              summary: "nvidia-smi timed out",
              hint: "other checks still work",
              code: "gpu_probe_failed",
            },
          ],
        },
      },
    });
    expect(partial.phase).toBe("ready");
    expect(partial.checks.map((item) => item.id)).toEqual([
      "python",
      "node",
      "data_dir",
      "sqlite",
      "ollama",
      "milvus",
      "ram",
      "gpu",
    ]);
    expect(partial.checks.find((item) => item.id === "milvus")?.code).toBe(
      "partial_missing",
    );
    expect(checkExtraLabel(partial.checks.find((item) => item.id === "gpu")!)).toBe(
      "GPU 探测失败",
    );
  });

  it("keeps previous checks visible while a refresh is in flight", () => {
    const previous = {
      generated_at: "2026-09-21T00:00:00Z",
      overall_status: "error" as const,
      copy_summary: "ollama down",
      checks: [
        {
          id: "ollama",
          label: "Ollama",
          status: "error" as const,
          summary: "Ollama is not reachable.",
          hint: "Start Ollama locally.",
        },
      ],
    };
    const refreshing = diagnosticsView({
      previous,
      incoming: { type: "loading" },
    });
    expect(refreshing.phase).toBe("ready");
    expect(refreshing.checks.find((item) => item.id === "ollama")?.status).toBe(
      "error",
    );
  });
});
