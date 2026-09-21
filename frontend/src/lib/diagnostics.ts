export type CheckStatus = "ok" | "warning" | "error";
export type GpuPresence = "ok" | "absent" | "probe_failed" | "unknown";

export function overallLabel(status: CheckStatus): string {
  if (status === "ok") return "正常";
  if (status === "warning") return "警告";
  return "异常";
}

export function statusClassName(status: CheckStatus): string {
  if (status === "ok")
    return "border-emerald-200 bg-emerald-50 text-emerald-900";
  if (status === "warning")
    return "border-amber-200 bg-amber-50 text-amber-900";
  return "border-red-200 bg-red-50 text-red-900";
}

export function gpuPresenceFromCode(
  code: string | null | undefined,
): GpuPresence {
  if (code === "gpu_ok") return "ok";
  if (code === "gpu_absent") return "absent";
  if (code === "gpu_probe_failed") return "probe_failed";
  return "unknown";
}

export function gpuPresenceLabel(kind: GpuPresence): string {
  if (kind === "ok") return "已检测到 GPU";
  if (kind === "absent") return "无 NVIDIA GPU";
  if (kind === "probe_failed") return "GPU 探测失败";
  return "GPU 状态未知";
}

export function summaryLooksPrivate(
  copySummary: string,
  novelBody: string,
): boolean {
  return !copySummary.includes(novelBody);
}
