export type CheckStatus = "ok" | "warning" | "error";

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

export function summaryLooksPrivate(
  copySummary: string,
  novelBody: string,
): boolean {
  return !copySummary.includes(novelBody);
}
