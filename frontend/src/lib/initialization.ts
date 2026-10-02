export type InitPhase = {
  id: string;
  label: string;
  detail: string;
  status: string;
};

export type InitializationStatus = {
  run_id: string | null;
  novel_id: string;
  state: string;
  current_phase: string | null;
  phase_label: string;
  phases: InitPhase[];
  progress_done: number;
  progress_total: number;
  error_code: string | null;
  error_message: string | null;
  suggested_action: string | null;
  ready: boolean;
};

export type WritingGate = {
  ready: boolean;
  state: string;
  message: string;
};

export function initializePath(novelId: string): string {
  return `/novels/${novelId}/initialize`;
}

export function writingPath(novelId: string): string {
  return `/novels/${novelId}/write`;
}

export function initView(
  status: InitializationStatus | null,
  loading: boolean,
  error: string | null,
) {
  if (loading)
    return {
      headline: "正在读取初始化状态…",
      canStart: false,
      canResume: false,
    };
  if (error) return { headline: error, canStart: false, canResume: false };
  if (!status || status.state === "not_started") {
    return { headline: "尚未开始", canStart: true, canResume: false };
  }
  return {
    headline: status.phase_label,
    canStart: status.state === "not_started",
    canResume: status.state === "paused" || status.state === "failed",
  };
}

export function writingView(gate: WritingGate | null) {
  if (!gate) return { ready: false, message: "还不能续写。" };
  return { ready: gate.ready, message: gate.message };
}

export function visiblePhases(phases: InitPhase[]): InitPhase[] {
  const order = ["分析章节", "构建记忆", "准备检索索引", "完成"];
  const grouped = new Map<string, InitPhase>();
  for (const phase of phases) {
    const current = grouped.get(phase.label);
    if (!current || rank(phase.status) > rank(current.status))
      grouped.set(phase.label, phase);
  }
  return order
    .map((label) => grouped.get(label))
    .filter((phase): phase is InitPhase => phase !== undefined);
}

function rank(status: string): number {
  if (status === "completed") return 3;
  if (status === "failed") return 2;
  if (status === "running" || status === "paused") return 1;
  return 0;
}
