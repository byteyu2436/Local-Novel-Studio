import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

export default function ImportPreviewPlaceholderPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-8 px-6 py-16">
      <div className="space-y-3">
        <p className="text-sm font-medium uppercase tracking-[0.18em] text-muted-foreground">
          导入小说
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">确认章节</h1>
        <p className="max-w-2xl text-lg leading-7 text-muted-foreground">
          正文已保存。下一步会识别单章、多章或无明确章节结构，并让你确认后再创建章节。
        </p>
      </div>
      <div className="flex flex-wrap gap-3">
        <Button asChild>
          <Link to="/import">返回修改正文</Link>
        </Button>
        <Button asChild variant="outline">
          <Link to="/">返回首页</Link>
        </Button>
      </div>
    </main>
  );
}
