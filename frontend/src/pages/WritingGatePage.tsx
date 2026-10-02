import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  initializePath,
  writingView,
  type WritingGate,
} from "@/lib/initialization";
import { workspacePath } from "@/lib/writing";

export default function WritingGatePage() {
  const { novelId = "" } = useParams();
  const [gate, setGate] = useState<WritingGate | null>(null);
  const view = writingView(gate);

  useEffect(() => {
    void fetch(`/api/novels/${novelId}/writing-gate`)
      .then((response) => (response.ok ? response.json() : null))
      .then((body: WritingGate | null) => setGate(body));
  }, [novelId]);

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-10">
      <h1 className="text-3xl font-semibold">
        {view.ready ? "可以续写" : "还不能续写"}
      </h1>
      <p>{view.message}</p>
      {view.ready ? (
        <Button asChild>
          <Link to={workspacePath(novelId)}>进入续写</Link>
        </Button>
      ) : (
        <Button asChild>
          <Link to={initializePath(novelId)}>去完成初始化</Link>
        </Button>
      )}
    </main>
  );
}
