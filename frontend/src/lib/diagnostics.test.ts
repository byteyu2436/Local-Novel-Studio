import { describe, expect, it } from "vitest";

import {
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
});
