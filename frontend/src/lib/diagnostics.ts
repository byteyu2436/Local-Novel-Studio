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

export const CORE_CHECK_IDS = [
  "python",
  "node",
  "data_dir",
  "sqlite",
  "ollama",
  "milvus",
  "ram",
  "gpu",
] as const;

export type CoreCheckId = (typeof CORE_CHECK_IDS)[number];

export const CORE_CHECK_LABELS: Record<CoreCheckId, string> = {
  python: "Python",
  node: "Node.js",
  data_dir: "数据目录",
  sqlite: "SQLite",
  ollama: "Ollama",
  milvus: "Milvus",
  ram: "RAM",
  gpu: "GPU",
};

export type DiagnosticCheck = {
  id: string;
  label: string;
  status: CheckStatus;
  summary: string;
  hint: string | null;
  code?: string | null;
};

export type DiagnosticsResponse = {
  generated_at: string;
  overall_status: CheckStatus;
  checks: DiagnosticCheck[];
  copy_summary: string;
};

const LOADING_ERROR =
  "无法读取诊断接口。请先运行 scripts/dev-backend.ps1，然后刷新。";

export type DiagnosticsView = {
  phase: "loading" | "error" | "ready";
  data: DiagnosticsResponse | null;
  error: string | null;
  checks: DiagnosticCheck[];
};

export function isDiagnosticsResponse(
  value: unknown,
): value is DiagnosticsResponse {
  if (!value || typeof value !== "object") return false;
  const payload = value as DiagnosticsResponse;
  return (
    typeof payload.generated_at === "string" &&
    (payload.overall_status === "ok" ||
      payload.overall_status === "warning" ||
      payload.overall_status === "error") &&
    Array.isArray(payload.checks) &&
    typeof payload.copy_summary === "string"
  );
}

export function withPartialChecks(
  checks: DiagnosticCheck[],
): DiagnosticCheck[] {
  const byId = new Map(checks.map((check) => [check.id, check]));
  return CORE_CHECK_IDS.map((id) => {
    const existing = byId.get(id);
    if (existing) return existing;
    return {
      id,
      label: CORE_CHECK_LABELS[id],
      status: "warning",
      summary: "该项未从诊断接口返回。",
      hint: "刷新诊断。其它检查项仍可查看。",
      code: "partial_missing",
    };
  });
}

export function diagnosticsView(args: {
  previous: DiagnosticsResponse | null;
  incoming:
    | { type: "loading" }
    | { type: "error" }
    | { type: "ok"; payload: unknown };
}): DiagnosticsView {
  if (args.incoming.type === "loading") {
    return {
      phase: args.previous ? "ready" : "loading",
      data: args.previous,
      error: null,
      checks: args.previous ? withPartialChecks(args.previous.checks) : [],
    };
  }
  if (args.incoming.type === "error") {
    return {
      phase: "error",
      data: args.previous,
      error: LOADING_ERROR,
      checks: args.previous ? withPartialChecks(args.previous.checks) : [],
    };
  }
  if (!isDiagnosticsResponse(args.incoming.payload)) {
    return {
      phase: "error",
      data: args.previous,
      error: LOADING_ERROR,
      checks: args.previous ? withPartialChecks(args.previous.checks) : [],
    };
  }
  return {
    phase: "ready",
    data: args.incoming.payload,
    error: null,
    checks: withPartialChecks(args.incoming.payload.checks),
  };
}

export function checkExtraLabel(check: DiagnosticCheck): string | null {
  if (check.id !== "gpu") return null;
  const presence = gpuPresenceFromCode(check.code);
  if (presence === "unknown") return null;
  return gpuPresenceLabel(presence);
}
